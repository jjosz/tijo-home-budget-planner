from datetime import date, datetime
from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from app.services import BudgetService, CalendarService

main_bp = Blueprint("main", __name__)


def _get_service() -> BudgetService:
    return BudgetService(
        budget_repo=current_app.config["BUDGET_REPOSITORY"],
        tx_repo=current_app.config["TRANSACTION_REPOSITORY"],
        recurring_repo=current_app.config["RECURRING_REPOSITORY"]
    )


def _parse_int_or_none(raw_value: str | None) -> int | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    return int(raw_value)


def _extract_short_month_days(prefix: str) -> dict[str, int | None]:
    return {
        "30": _parse_int_or_none(request.form.get(f"{prefix}_30")),
        "29": _parse_int_or_none(request.form.get(f"{prefix}_29")),
        "28": _parse_int_or_none(request.form.get(f"{prefix}_28"))
    }


def _parse_iso_date(iso_str: str) -> date:
    try:
        return datetime.strptime(iso_str, "%Y-%m-%d").date()
    except ValueError:
        abort(404)


def _resolve_requested_year_month() -> tuple[int, int]:
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        if not (1 <= month <= 12 and 1970 <= year <= 2100):
            return today.year, today.month
        return year, month
    except ValueError:
        return today.year, today.month


@main_bp.route("/")
def index():
    budget_repo = current_app.config["BUDGET_REPOSITORY"]
    budget_data = budget_repo.get_budget_data()

    if budget_data is None:
        return render_template("index.html", budget_data=None, calendar_data=None, error=None)

    year, month = _resolve_requested_year_month()
    today = date.today()
    tx_repo = current_app.config["TRANSACTION_REPOSITORY"]
    rec_repo = current_app.config["RECURRING_REPOSITORY"]

    calendar_data = CalendarService.build_month_view(
        year=year,
        month=month,
        budget_data=budget_data,
        month_one_time=tx_repo.get_month_transactions(year, month),
        current_month_one_time=tx_repo.get_month_transactions(today.year, today.month),
        recurring_definitions=rec_repo.get_all()
    )

    return render_template(
        "index.html",
        budget_data=budget_data,
        calendar_data=calendar_data,
        error=None
    )


@main_bp.route("/setup", methods=["POST"])
def setup_budget():
    service = _get_service()
    try:
        reset_day = int(request.form.get("reset_day", 0))
        reset_short_days = _extract_short_month_days("reset_short")
        initial_budget = float(request.form.get("initial_budget", 0))

        lock_mode = request.form.get("lock_mode", "NEVER")
        lock_day = _parse_int_or_none(request.form.get("lock_day"))
        lock_short_days = _extract_short_month_days("lock_short")

        service.initialize_budget(
            reset_day=reset_day,
            reset_short_days=reset_short_days,
            initial_budget=initial_budget,
            lock_mode=lock_mode,
            lock_day=lock_day,
            lock_short_days=lock_short_days
        )
        return redirect(url_for("main.index"))
    except ValueError as err:
        return render_template(
            "index.html",
            budget_data=None,
            calendar_data=None,
            error=str(err),
            show_form=True
        ), 400


@main_bp.route("/day/<iso_date>")
def day_view(iso_date: str):
    target_date = _parse_iso_date(iso_date)
    service = _get_service()
    try:
        details = service.get_day_details(target_date)
    except ValueError:
        return redirect(url_for("main.index"))

    return render_template("day.html", details=details, error=request.args.get("error"))


@main_bp.route("/day/<iso_date>/add", methods=["POST"])
def add_transaction(iso_date: str):
    target_date = _parse_iso_date(iso_date)
    service = _get_service()
    try:
        service.add_one_time_transaction(
            target_date=target_date,
            title=request.form.get("title", ""),
            description=request.form.get("description", ""),
            amount=float(request.form.get("amount", 0)),
            tx_type=request.form.get("tx_type", "EXPENSE")
        )
        return redirect(url_for("main.day_view", iso_date=iso_date))
    except (ValueError, PermissionError) as err:
        return redirect(url_for("main.day_view", iso_date=iso_date, error=str(err)))


@main_bp.route("/day/<iso_date>/add-recurring", methods=["POST"])
def add_recurring_transaction(iso_date: str):
    target_date = _parse_iso_date(iso_date)
    service = _get_service()
    try:
        service.add_recurring_transaction(
            target_date=target_date,
            title=request.form.get("title", ""),
            description=request.form.get("description", ""),
            amount=float(request.form.get("amount", 0)),
            tx_type=request.form.get("tx_type", "EXPENSE"),
            short_month_days=_extract_short_month_days("rec_short")
        )
        return redirect(url_for("main.day_view", iso_date=iso_date))
    except (ValueError, PermissionError) as err:
        return redirect(url_for("main.day_view", iso_date=iso_date, error=str(err)))


@main_bp.route("/day/<iso_date>/edit", methods=["POST"])
def edit_item(iso_date: str):
    target_date = _parse_iso_date(iso_date)
    service = _get_service()
    item_id = request.form.get("item_id", "")
    is_recurring = request.form.get("is_recurring") == "true"

    try:
        title = request.form.get("title", "")
        description = request.form.get("description", "")
        amount = float(request.form.get("amount", 0))
        tx_type = request.form.get("tx_type", "EXPENSE")

        if is_recurring:
            service.update_recurring_transaction(target_date, item_id, title, description, amount, tx_type)
        else:
            service.update_one_time_transaction(target_date, item_id, title, description, amount, tx_type)
        return redirect(url_for("main.day_view", iso_date=iso_date))
    except (ValueError, PermissionError) as err:
        return redirect(url_for("main.day_view", iso_date=iso_date, error=str(err)))


@main_bp.route("/day/<iso_date>/delete", methods=["POST"])
def delete_item(iso_date: str):
    target_date = _parse_iso_date(iso_date)
    service = _get_service()
    item_id = request.form.get("item_id", "")
    is_recurring = request.form.get("is_recurring") == "true"
    scope = request.form.get("scope", "MONTH_ONLY")

    try:
        if is_recurring:
            service.remove_recurring_instance(target_date, item_id, scope)
        else:
            service.delete_one_time_transaction(target_date, item_id)
        return redirect(url_for("main.day_view", iso_date=iso_date))
    except (ValueError, PermissionError) as err:
        return redirect(url_for("main.day_view", iso_date=iso_date, error=str(err)))

@main_bp.route("/settings")
def settings_view():
    budget_repo = current_app.config["BUDGET_REPOSITORY"]
    if budget_repo.get_budget_data() is None:
        return redirect(url_for("main.index"))

    service = _get_service()
    recurring_list = service.get_all_recurring()
    return render_template(
        "settings.html",
        recurring_list=recurring_list,
        error=request.args.get("error"),
        success=request.args.get("success")
    )


@main_bp.route("/settings/recurring/edit", methods=["POST"])
def settings_edit_recurring():
    service = _get_service()
    rec_id = request.form.get("rec_id", "")
    try:
        service.update_recurring_transaction(
            target_date=date.today(),
            rec_id=rec_id,
            title=request.form.get("title", ""),
            description=request.form.get("description", ""),
            amount=float(request.form.get("amount", 0)),
            tx_type=request.form.get("tx_type", "EXPENSE")
        )
        return redirect(url_for("main.settings_view", success="Zapisano zmiany w subskrypcji."))
    except (ValueError, PermissionError) as err:
        return redirect(url_for("main.settings_view", error=str(err)))


@main_bp.route("/settings/recurring/delete", methods=["POST"])
def settings_delete_recurring():
    service = _get_service()
    rec_id = request.form.get("rec_id", "")
    try:
        service.delete_recurring_completely(rec_id)
        return redirect(url_for("main.settings_view", success="Subskrypcja została zakończona/usunięta."))
    except (ValueError, PermissionError) as err:
        return redirect(url_for("main.settings_view", error=str(err)))