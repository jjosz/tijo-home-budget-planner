from datetime import date, datetime
from typing import Any, Callable, Dict, Optional, Tuple
from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from app.services import (
    BudgetConfigurationService,
    CalendarViewBuilder,
    DayDetailsService,
    RecurringScheduleService,
    TransactionManagementService,
)

main_bp = Blueprint("main", __name__)


def _get_current_date() -> date:
    clock_provider: Optional[Callable[[], date]] = current_app.config.get("CLOCK_PROVIDER")
    if clock_provider is not None:
        return clock_provider()
    return date.today()


def _get_services() -> Dict[str, Any]:
    return current_app.config["APPLICATION_SERVICES"]


def _parse_optional_int(raw_value: Optional[str]) -> Optional[int]:
    if raw_value is None or raw_value.strip() == "":
        return None
    return int(raw_value)


def _extract_short_month_overrides(prefix: str) -> Dict[str, Optional[int]]:
    return {
        "30": _parse_optional_int(request.form.get(f"{prefix}_30")),
        "29": _parse_optional_int(request.form.get(f"{prefix}_29")),
        "28": _parse_optional_int(request.form.get(f"{prefix}_28")),
    }


def _parse_iso_date(date_text: str) -> date:
    try:
        return datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError:
        abort(404)


def _resolve_requested_year_month(reference_date: date) -> Tuple[int, int]:
    try:
        year = int(request.args.get("year", reference_date.year))
        month = int(request.args.get("month", reference_date.month))
        if 1 <= month <= 12 and 1970 <= year <= 2100:
            return year, month
        return reference_date.year, reference_date.month
    except ValueError:
        return reference_date.year, reference_date.month


def _extract_entry_form_data() -> Tuple[str, str, float, str]:
    title = request.form.get("title", "")
    description = request.form.get("description", "")
    amount = float(request.form.get("amount", 0))
    transaction_type = request.form.get("tx_type", "EXPENSE")
    return title, description, amount, transaction_type


@main_bp.route("/")
def index() -> Any:
    budget_repository = current_app.config["BUDGET_REPOSITORY"]
    budget_configuration = budget_repository.get_budget_configuration()

    if budget_configuration is None:
        return render_template(
            "index.html",
            budget_data=None,
            calendar_data=None,
            error=None,
        )

    current_date = _get_current_date()
    year, month = _resolve_requested_year_month(current_date)
    transaction_repository = current_app.config["TRANSACTION_REPOSITORY"]
    recurring_repository = current_app.config["RECURRING_REPOSITORY"]
    lock_evaluator = current_app.config["LOCK_POLICY_EVALUATOR"]

    calendar_builder = CalendarViewBuilder(lock_evaluator=lock_evaluator)
    calendar_data = calendar_builder.build_month_view(
        year=year,
        month=month,
        budget_configuration=budget_configuration,
        month_one_time=transaction_repository.get_month_transactions(year, month),
        current_month_one_time=transaction_repository.get_month_transactions(
            current_date.year,
            current_date.month,
        ),
        recurring_definitions=recurring_repository.get_all_definitions(),
        current_date=current_date,
    )

    return render_template(
        "index.html",
        budget_data=budget_configuration,
        calendar_data=calendar_data,
        error=None,
    )


@main_bp.route("/setup", methods=["POST"])
def setup_budget() -> Any:
    configuration_service: BudgetConfigurationService = _get_services()["budget_configuration_service"]
    try:
        reset_day = int(request.form.get("reset_day", 0))
        reset_short_days = _extract_short_month_overrides("reset_short")
        initial_budget = float(request.form.get("initial_budget", 0))
        lock_mode = request.form.get("lock_mode", "NEVER")
        lock_day = _parse_optional_int(request.form.get("lock_day"))
        lock_short_days = _extract_short_month_overrides("lock_short")

        configuration_service.initialize_budget(
            reset_day=reset_day,
            reset_short_days=reset_short_days,
            initial_budget=initial_budget,
            lock_mode=lock_mode,
            lock_day=lock_day,
            lock_short_days=lock_short_days,
        )
        return redirect(url_for("main.index"))
    except ValueError as validation_error:
        return (
            render_template(
                "index.html",
                budget_data=None,
                calendar_data=None,
                error=str(validation_error),
                show_form=True,
            ),
            400,
        )


@main_bp.route("/day/<iso_date>")
def day_view(iso_date: str) -> Any:
    target_date = _parse_iso_date(iso_date)
    current_date = _get_current_date()
    day_details_service: DayDetailsService = _get_services()["day_details_service"]

    try:
        details = day_details_service.get_day_details(target_date=target_date, current_date=current_date)
    except ValueError:
        return redirect(url_for("main.index"))

    return render_template("day.html", details=details, error=request.args.get("error"))


@main_bp.route("/day/<iso_date>/add", methods=["POST"])
def add_transaction(iso_date: str) -> Any:
    target_date = _parse_iso_date(iso_date)
    current_date = _get_current_date()
    transaction_service: TransactionManagementService = _get_services()["transaction_management_service"]

    try:
        title, description, amount, transaction_type = _extract_entry_form_data()
        transaction_service.add_transaction(
            target_date=target_date,
            current_date=current_date,
            title=title,
            description=description,
            amount=amount,
            transaction_type=transaction_type,
        )
        return redirect(url_for("main.day_view", iso_date=iso_date))
    except (ValueError, PermissionError) as operation_error:
        return redirect(url_for("main.day_view", iso_date=iso_date, error=str(operation_error)))


@main_bp.route("/day/<iso_date>/add-recurring", methods=["POST"])
def add_recurring_transaction(iso_date: str) -> Any:
    target_date = _parse_iso_date(iso_date)
    current_date = _get_current_date()
    transaction_service: TransactionManagementService = _get_services()["transaction_management_service"]
    recurring_service: RecurringScheduleService = _get_services()["recurring_schedule_service"]

    try:
        transaction_service.ensure_unlocked(target_date=target_date, current_date=current_date)
        title, description, amount, transaction_type = _extract_entry_form_data()
        recurring_service.create_recurring(
            target_date=target_date,
            title=title,
            description=description,
            amount=amount,
            transaction_type=transaction_type,
            short_month_days=_extract_short_month_overrides("rec_short"),
        )
        return redirect(url_for("main.day_view", iso_date=iso_date))
    except (ValueError, PermissionError) as operation_error:
        return redirect(url_for("main.day_view", iso_date=iso_date, error=str(operation_error)))


@main_bp.route("/day/<iso_date>/edit", methods=["POST"])
def edit_item(iso_date: str) -> Any:
    target_date = _parse_iso_date(iso_date)
    current_date = _get_current_date()
    transaction_service: TransactionManagementService = _get_services()["transaction_management_service"]
    recurring_service: RecurringScheduleService = _get_services()["recurring_schedule_service"]

    item_id = request.form.get("item_id", "")
    is_recurring = request.form.get("is_recurring") == "true"

    try:
        transaction_service.ensure_unlocked(target_date=target_date, current_date=current_date)
        title, description, amount, transaction_type = _extract_entry_form_data()
        if is_recurring:
            recurring_service.update_recurring(
                recurring_id=item_id,
                title=title,
                description=description,
                amount=amount,
                transaction_type=transaction_type,
            )
        else:
            transaction_service.update_transaction(
                target_date=target_date,
                current_date=current_date,
                transaction_id=item_id,
                title=title,
                description=description,
                amount=amount,
                transaction_type=transaction_type,
            )
        return redirect(url_for("main.day_view", iso_date=iso_date))
    except (ValueError, PermissionError) as operation_error:
        return redirect(url_for("main.day_view", iso_date=iso_date, error=str(operation_error)))


@main_bp.route("/day/<iso_date>/delete", methods=["POST"])
def delete_item(iso_date: str) -> Any:
    target_date = _parse_iso_date(iso_date)
    current_date = _get_current_date()
    transaction_service: TransactionManagementService = _get_services()["transaction_management_service"]
    recurring_service: RecurringScheduleService = _get_services()["recurring_schedule_service"]

    item_id = request.form.get("item_id", "")
    is_recurring = request.form.get("is_recurring") == "true"
    removal_scope = request.form.get("scope", "MONTH_ONLY")

    try:
        transaction_service.ensure_unlocked(target_date=target_date, current_date=current_date)
        if is_recurring:
            recurring_service.remove_occurrence(
                target_date=target_date,
                recurring_id=item_id,
                removal_scope=removal_scope,
            )
        else:
            transaction_service.delete_transaction(
                target_date=target_date,
                current_date=current_date,
                transaction_id=item_id,
            )
        return redirect(url_for("main.day_view", iso_date=iso_date))
    except (ValueError, PermissionError) as operation_error:
        return redirect(url_for("main.day_view", iso_date=iso_date, error=str(operation_error)))


@main_bp.route("/settings")
def settings_view() -> Any:
    budget_repository = current_app.config["BUDGET_REPOSITORY"]
    if budget_repository.get_budget_configuration() is None:
        return redirect(url_for("main.index"))

    recurring_service: RecurringScheduleService = _get_services()["recurring_schedule_service"]
    return render_template(
        "settings.html",
        recurring_list=recurring_service.get_all_definitions(),
        error=request.args.get("error"),
        success=request.args.get("success"),
    )


@main_bp.route("/settings/recurring/edit", methods=["POST"])
def settings_edit_recurring() -> Any:
    recurring_service: RecurringScheduleService = _get_services()["recurring_schedule_service"]
    recurring_id = request.form.get("rec_id", "")
    try:
        title, description, amount, transaction_type = _extract_entry_form_data()
        recurring_service.update_recurring(
            recurring_id=recurring_id,
            title=title,
            description=description,
            amount=amount,
            transaction_type=transaction_type,
        )
        return redirect(url_for("main.settings_view", success="Zapisano zmiany w subskrypcji."))
    except ValueError as validation_error:
        return redirect(url_for("main.settings_view", error=str(validation_error)))


@main_bp.route("/settings/recurring/delete", methods=["POST"])
def settings_delete_recurring() -> Any:
    recurring_service: RecurringScheduleService = _get_services()["recurring_schedule_service"]
    recurring_id = request.form.get("rec_id", "")
    current_date = _get_current_date()
    try:
        recurring_service.remove_occurrence(
            target_date=current_date,
            recurring_id=recurring_id,
            removal_scope="ENTIRE_SUBSCRIPTION",
        )
        return redirect(url_for("main.settings_view", success="Subskrypcja została zakończona/usunięta."))
    except ValueError as validation_error:
        return redirect(url_for("main.settings_view", error=str(validation_error)))