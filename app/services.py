import calendar
from datetime import date
from typing import Any, Dict, List, Optional, Protocol, Tuple


class LockEvaluationStrategy(Protocol):
    def is_locked(
        self,
        target_date: date,
        current_date: date,
        lock_policy: Dict[str, Any],
    ) -> bool:
        ...


class ShortMonthDayResolver:
    @staticmethod
    def resolve_day(year: int, month: int, day_rule: Dict[str, Any]) -> int:
        configured_day = int(day_rule.get("day", 1))
        max_days_in_month = calendar.monthrange(year, month)[1]
        if configured_day <= max_days_in_month:
            return configured_day

        short_month_overrides = day_rule.get("short_month_days") or {}
        override_day = short_month_overrides.get(str(max_days_in_month))
        if override_day is not None:
            return min(int(override_day), max_days_in_month)
        return max_days_in_month


class BudgetInputValidator:
    VALID_LOCK_MODES = {"NEVER", "LAST_DAY", "SPECIFIC_DAY"}
    VALID_TRANSACTION_TYPES = {"EXPENSE", "INCOME"}

    @staticmethod
    def validate_day_rule(
        base_day: int,
        short_month_days: Dict[str, Optional[int]],
        field_label: str,
    ) -> Dict[str, Any]:
        if not 1 <= base_day <= 31:
            raise ValueError(f"{field_label}: day must be between 1 and 31.")

        required_month_lengths: List[int] = []
        if base_day >= 31:
            required_month_lengths.append(30)
        if base_day >= 30:
            required_month_lengths.append(29)
        if base_day >= 29:
            required_month_lengths.append(28)

        validated_overrides: Dict[str, int] = {}
        for month_length in required_month_lengths:
            raw_override = short_month_days.get(str(month_length))
            if raw_override is None or not (1 <= raw_override <= month_length):
                raise ValueError(
                    f"{field_label}: day for {month_length}-day months must be between 1 and {month_length}."
                )
            validated_overrides[str(month_length)] = raw_override

        return {
            "day": base_day,
            "short_month_days": validated_overrides,
        }

    @staticmethod
    def validate_positive_amount(amount: float, field_label: str = "Amount") -> None:
        if amount <= 0:
            raise ValueError(f"{field_label} must be greater than zero.")

    @classmethod
    def validate_lock_policy(
        cls,
        lock_mode: str,
        lock_day: Optional[int],
        short_month_days: Dict[str, Optional[int]],
    ) -> Dict[str, Any]:
        if lock_mode not in cls.VALID_LOCK_MODES:
            raise ValueError("Invalid lock mode selected.")
        if lock_mode in {"NEVER", "LAST_DAY"}:
            return {"mode": lock_mode, "rule": None}
        if lock_day is None:
            raise ValueError("Lock day is required for specific day mode.")

        rule = cls.validate_day_rule(lock_day, short_month_days, "Lock day")
        return {"mode": lock_mode, "rule": rule}

    @classmethod
    def validate_transaction_input(
        cls,
        title: str,
        amount: float,
        transaction_type: str,
    ) -> None:
        if not title or len(title.strip()) < 2:
            raise ValueError("Title must contain at least 2 characters.")
        cls.validate_positive_amount(amount, "Amount")
        if transaction_type not in cls.VALID_TRANSACTION_TYPES:
            raise ValueError("Transaction type must be EXPENSE or INCOME.")


class StandardLockEvaluationStrategy:
    @staticmethod
    def _next_month_year_and_month(target_date: date) -> Tuple[int, int]:
        if target_date.month == 12:
            return target_date.year + 1, 1
        return target_date.year, target_date.month + 1

    def is_locked(
        self,
        target_date: date,
        current_date: date,
        lock_policy: Dict[str, Any],
    ) -> bool:
        mode = lock_policy.get("mode", "NEVER")
        if mode == "NEVER":
            return False

        next_year, next_month = self._next_month_year_and_month(target_date)
        max_days_next_month = calendar.monthrange(next_year, next_month)[1]

        if mode == "LAST_DAY":
            effective_lock_day = max_days_next_month
        else:
            rule = lock_policy.get("rule") or {"day": 1, "short_month_days": {}}
            effective_lock_day = ShortMonthDayResolver.resolve_day(next_year, next_month, rule)

        lock_deadline = date(next_year, next_month, effective_lock_day)
        return current_date > lock_deadline


class BudgetLockPolicyEvaluator:
    def __init__(self, strategy: Optional[LockEvaluationStrategy] = None) -> None:
        self._strategy: LockEvaluationStrategy = strategy or StandardLockEvaluationStrategy()

    def is_date_locked(
        self,
        target_date: date,
        current_date: date,
        lock_policy: Optional[Dict[str, Any]],
    ) -> bool:
        if not lock_policy:
            return False
        return self._strategy.is_locked(target_date, current_date, lock_policy)


class RecurringScheduleService:
    def __init__(self, recurring_repository: Any) -> None:
        self._recurring_repository = recurring_repository

    def get_all_definitions(self) -> List[Dict[str, Any]]:
        return self._recurring_repository.get_all_definitions()

    @staticmethod
    def build_month_occurrences(
        recurring_definitions: List[Dict[str, Any]],
        year: int,
        month: int,
        reference_date: date,
    ) -> Dict[int, List[Dict[str, Any]]]:
        if (year, month) > (reference_date.year, reference_date.month):
            return {}

        month_tag = f"{month:02d}-{year}"
        occurrences_by_day: Dict[int, List[Dict[str, Any]]] = {}

        for definition in recurring_definitions:
            if not RecurringScheduleService._is_active_in_month(definition, year, month, month_tag):
                continue

            resolved_day = ShortMonthDayResolver.resolve_day(year, month, definition["day_rule"])
            occurrence = {
                "id": definition["id"],
                "title": definition["title"],
                "description": definition.get("description", ""),
                "amount": definition["amount"],
                "type": definition["type"],
                "is_recurring": True,
            }
            occurrences_by_day.setdefault(resolved_day, []).append(occurrence)

        return occurrences_by_day

    @staticmethod
    def _is_active_in_month(
        definition: Dict[str, Any],
        year: int,
        month: int,
        month_tag: str,
    ) -> bool:
        if (year, month) < (definition["start_year"], definition["start_month"]):
            return False

        end_year = definition.get("end_year")
        end_month = definition.get("end_month")
        if end_year is not None and end_month is not None:
            if (year, month) > (end_year, end_month):
                return False

        return month_tag not in definition.get("skipped_months", [])

    def create_recurring(
        self,
        target_date: date,
        title: str,
        description: str,
        amount: float,
        transaction_type: str,
        short_month_days: Dict[str, Optional[int]],
    ) -> None:
        BudgetInputValidator.validate_transaction_input(title, amount, transaction_type)
        day_rule = BudgetInputValidator.validate_day_rule(
            target_date.day,
            short_month_days,
            "Recurring day",
        )
        self._recurring_repository.add_definition(
            title=title.strip(),
            description=description.strip(),
            amount=amount,
            transaction_type=transaction_type,
            start_year=target_date.year,
            start_month=target_date.month,
            day_rule=day_rule,
        )

    def update_recurring(
        self,
        recurring_id: str,
        title: str,
        description: str,
        amount: float,
        transaction_type: str,
    ) -> None:
        BudgetInputValidator.validate_transaction_input(title, amount, transaction_type)
        self._recurring_repository.update_definition(
            recurring_id=recurring_id,
            title=title.strip(),
            description=description.strip(),
            amount=amount,
            transaction_type=transaction_type,
        )

    def remove_occurrence(
        self,
        target_date: date,
        recurring_id: str,
        removal_scope: str,
    ) -> None:
        if removal_scope == "MONTH_ONLY":
            self._recurring_repository.skip_month(
                recurring_id=recurring_id,
                year=target_date.year,
                month=target_date.month,
            )
        elif removal_scope == "ENTIRE_SUBSCRIPTION":
            self._recurring_repository.stop_or_remove_definition(
                recurring_id=recurring_id,
                effective_year=target_date.year,
                effective_month=target_date.month,
            )
        else:
            raise ValueError("Invalid removal scope.")


class BudgetMetricsCalculator:
    @staticmethod
    def calculate_daily_average(monthly_budget: float, year: int, month: int) -> float:
        days_in_month = calendar.monthrange(year, month)[1]
        return round(monthly_budget / days_in_month, 2)

    @staticmethod
    def _sum_entries(entries: List[Dict[str, Any]]) -> Tuple[float, float]:
        expenses = 0.0
        incomes = 0.0
        for entry in entries:
            if entry.get("type") == "EXPENSE":
                expenses += float(entry.get("amount", 0.0))
            elif entry.get("type") == "INCOME":
                incomes += float(entry.get("amount", 0.0))
        return expenses, incomes

    @classmethod
    def calculate_month_summary(
        cls,
        monthly_budget: float,
        month_one_time: Dict[str, List[Dict[str, Any]]],
        month_recurring: Dict[int, List[Dict[str, Any]]],
    ) -> Dict[str, float]:
        total_expenses = 0.0
        total_incomes = 0.0

        for day_transactions in month_one_time.values():
            exp, inc = cls._sum_entries(day_transactions)
            total_expenses += exp
            total_incomes += inc

        for day_recurring in month_recurring.values():
            exp, inc = cls._sum_entries(day_recurring)
            total_expenses += exp
            total_incomes += inc

        remaining_budget = round(monthly_budget + total_incomes - total_expenses, 2)
        return {
            "total_expenses": round(total_expenses, 2),
            "total_incomes": round(total_incomes, 2),
            "remaining_budget": remaining_budget,
        }

    @classmethod
    def evaluate_day_visuals(
        cls,
        day_entries: List[Dict[str, Any]],
        daily_average: float,
    ) -> Dict[str, Any]:
        expenses, incomes = cls._sum_entries(day_entries)
        rounded_expenses = round(expenses, 2)
        rounded_incomes = round(incomes, 2)

        if rounded_incomes > 0:
            status_color = "green"
        elif rounded_expenses > daily_average:
            status_color = "red"
        elif rounded_expenses > 0:
            status_color = "orange"
        else:
            status_color = "neutral"

        return {
            "expenses": rounded_expenses,
            "incomes": rounded_incomes,
            "status_color": status_color,
        }


class CalendarViewBuilder:
    MONTH_LABELS_PL = [
        "",
        "Styczeń",
        "Luty",
        "Marzec",
        "Kwiecień",
        "Maj",
        "Czerwiec",
        "Lipiec",
        "Sierpień",
        "Wrzesień",
        "Październik",
        "Listopad",
        "Grudzień",
    ]

    def __init__(self, lock_evaluator: BudgetLockPolicyEvaluator) -> None:
        self._lock_evaluator = lock_evaluator

    @staticmethod
    def get_previous_month(year: int, month: int) -> Tuple[int, int]:
        return (year - 1, 12) if month == 1 else (year, month - 1)

    @staticmethod
    def get_next_month(year: int, month: int) -> Tuple[int, int]:
        return (year + 1, 1) if month == 12 else (year, month + 1)

    def build_month_view(
        self,
        year: int,
        month: int,
        budget_configuration: Dict[str, Any],
        month_one_time: Dict[str, List[Dict[str, Any]]],
        current_month_one_time: Dict[str, List[Dict[str, Any]]],
        recurring_definitions: List[Dict[str, Any]],
        current_date: date,
    ) -> Dict[str, Any]:
        monthly_budget = float(budget_configuration["initial_budget"])
        lock_policy = budget_configuration.get("lock_policy")

        daily_average = BudgetMetricsCalculator.calculate_daily_average(monthly_budget, year, month)
        month_recurring = RecurringScheduleService.build_month_occurrences(
            recurring_definitions=recurring_definitions,
            year=year,
            month=month,
            reference_date=current_date,
        )
        viewed_summary = BudgetMetricsCalculator.calculate_month_summary(
            monthly_budget=monthly_budget,
            month_one_time=month_one_time,
            month_recurring=month_recurring,
        )
        current_summary = self._resolve_current_month_summary(
            year=year,
            month=month,
            monthly_budget=monthly_budget,
            current_month_one_time=current_month_one_time,
            recurring_definitions=recurring_definitions,
            current_date=current_date,
            viewed_summary=viewed_summary,
        )

        weeks = self._build_calendar_weeks(
            year=year,
            month=month,
            month_one_time=month_one_time,
            month_recurring=month_recurring,
            daily_average=daily_average,
            current_date=current_date,
            lock_policy=lock_policy,
        )
        previous_year, previous_month = self.get_previous_month(year, month)
        next_year, next_month = self.get_next_month(year, month)

        return {
            "year": year,
            "month": month,
            "month_label": f"{self.MONTH_LABELS_PL[month]} {year}",
            "current_month_label": f"{self.MONTH_LABELS_PL[current_date.month]} {current_date.year}",
            "current_month_remaining": current_summary["remaining_budget"],
            "viewed_month_remaining": viewed_summary["remaining_budget"],
            "viewed_month_expenses": viewed_summary["total_expenses"],
            "viewed_month_incomes": viewed_summary["total_incomes"],
            "daily_average": daily_average,
            "weeks": weeks,
            "prev_year": previous_year,
            "prev_month": previous_month,
            "next_year": next_year,
            "next_month": next_month,
        }

    @staticmethod
    def _resolve_current_month_summary(
        year: int,
        month: int,
        monthly_budget: float,
        current_month_one_time: Dict[str, List[Dict[str, Any]]],
        recurring_definitions: List[Dict[str, Any]],
        current_date: date,
        viewed_summary: Dict[str, float],
    ) -> Dict[str, float]:
        if (year, month) == (current_date.year, current_date.month):
            return viewed_summary

        current_recurring = RecurringScheduleService.build_month_occurrences(
            recurring_definitions=recurring_definitions,
            year=current_date.year,
            month=current_date.month,
            reference_date=current_date,
        )
        return BudgetMetricsCalculator.calculate_month_summary(
            monthly_budget=monthly_budget,
            month_one_time=current_month_one_time,
            month_recurring=current_recurring,
        )

    def _build_calendar_weeks(
        self,
        year: int,
        month: int,
        month_one_time: Dict[str, List[Dict[str, Any]]],
        month_recurring: Dict[int, List[Dict[str, Any]]],
        daily_average: float,
        current_date: date,
        lock_policy: Optional[Dict[str, Any]],
    ) -> List[List[Optional[Dict[str, Any]]]]:
        raw_weeks = calendar.monthcalendar(year, month)
        weeks: List[List[Optional[Dict[str, Any]]]] = []

        for raw_week in raw_weeks:
            formatted_week: List[Optional[Dict[str, Any]]] = []
            for day_number in raw_week:
                if day_number == 0:
                    formatted_week.append(None)
                    continue

                cell_date = date(year, month, day_number)
                day_key = f"{day_number:02d}-{month:02d}"
                combined_entries = month_one_time.get(day_key, []) + month_recurring.get(day_number, [])
                visuals = BudgetMetricsCalculator.evaluate_day_visuals(combined_entries, daily_average)

                formatted_week.append({
                    "day": day_number,
                    "iso_date": cell_date.isoformat(),
                    "is_today": cell_date == current_date,
                    "is_locked": self._lock_evaluator.is_date_locked(
                        target_date=cell_date,
                        current_date=current_date,
                        lock_policy=lock_policy,
                    ),
                    "expenses": visuals["expenses"],
                    "incomes": visuals["incomes"],
                    "status_color": visuals["status_color"],
                })
            weeks.append(formatted_week)

        return weeks


class BudgetConfigurationService:
    def __init__(self, budget_repository: Any) -> None:
        self._budget_repository = budget_repository

    def initialize_budget(
        self,
        reset_day: int,
        reset_short_days: Dict[str, Optional[int]],
        initial_budget: float,
        lock_mode: str,
        lock_day: Optional[int],
        lock_short_days: Dict[str, Optional[int]],
    ) -> None:
        reset_rule = BudgetInputValidator.validate_day_rule(
            reset_day,
            reset_short_days,
            "Reset day",
        )
        BudgetInputValidator.validate_positive_amount(initial_budget, "Initial budget")
        lock_policy = BudgetInputValidator.validate_lock_policy(
            lock_mode,
            lock_day,
            lock_short_days,
        )
        self._budget_repository.save_budget_configuration(
            initial_budget=initial_budget,
            reset_rule=reset_rule,
            lock_policy=lock_policy,
        )


class TransactionManagementService:
    def __init__(
        self,
        budget_repository: Any,
        transaction_repository: Any,
        lock_evaluator: BudgetLockPolicyEvaluator,
    ) -> None:
        self._budget_repository = budget_repository
        self._transaction_repository = transaction_repository
        self._lock_evaluator = lock_evaluator

    def ensure_unlocked(self, target_date: date, current_date: date) -> None:
        configuration = self._budget_repository.get_budget_configuration()
        if not configuration:
            raise ValueError("Budget is not initialized.")
        if self._lock_evaluator.is_date_locked(target_date, current_date, configuration.get("lock_policy")):
            raise PermissionError("This month is locked for editing.")

    def add_transaction(
        self,
        target_date: date,
        current_date: date,
        title: str,
        description: str,
        amount: float,
        transaction_type: str,
    ) -> None:
        self.ensure_unlocked(target_date, current_date)
        BudgetInputValidator.validate_transaction_input(title, amount, transaction_type)
        self._transaction_repository.add_transaction(
            target_date=target_date,
            title=title.strip(),
            description=description.strip(),
            amount=amount,
            transaction_type=transaction_type,
        )

    def update_transaction(
        self,
        target_date: date,
        current_date: date,
        transaction_id: str,
        title: str,
        description: str,
        amount: float,
        transaction_type: str,
    ) -> None:
        self.ensure_unlocked(target_date, current_date)
        BudgetInputValidator.validate_transaction_input(title, amount, transaction_type)
        self._transaction_repository.update_transaction(
            target_date=target_date,
            transaction_id=transaction_id,
            title=title.strip(),
            description=description.strip(),
            amount=amount,
            transaction_type=transaction_type,
        )

    def delete_transaction(
        self,
        target_date: date,
        current_date: date,
        transaction_id: str,
    ) -> None:
        self.ensure_unlocked(target_date, current_date)
        self._transaction_repository.delete_transaction(target_date, transaction_id)


class DayDetailsService:
    def __init__(
        self,
        budget_repository: Any,
        transaction_repository: Any,
        recurring_schedule_service: RecurringScheduleService,
        lock_evaluator: BudgetLockPolicyEvaluator,
    ) -> None:
        self._budget_repository = budget_repository
        self._transaction_repository = transaction_repository
        self._recurring_schedule_service = recurring_schedule_service
        self._lock_evaluator = lock_evaluator

    def get_day_details(self, target_date: date, current_date: date) -> Dict[str, Any]:
        configuration = self._budget_repository.get_budget_configuration()
        if not configuration:
            raise ValueError("Budget is not initialized.")

        monthly_budget = float(configuration["initial_budget"])
        month_one_time = self._transaction_repository.get_month_transactions(
            target_date.year,
            target_date.month,
        )
        recurring_definitions = self._recurring_schedule_service.get_all_definitions()
        month_recurring = self._recurring_schedule_service.build_month_occurrences(
            recurring_definitions=recurring_definitions,
            year=target_date.year,
            month=target_date.month,
            reference_date=current_date,
        )

        month_summary = BudgetMetricsCalculator.calculate_month_summary(
            monthly_budget=monthly_budget,
            month_one_time=month_one_time,
            month_recurring=month_recurring,
        )
        daily_average = BudgetMetricsCalculator.calculate_daily_average(
            monthly_budget=monthly_budget,
            year=target_date.year,
            month=target_date.month,
        )
        is_locked = self._lock_evaluator.is_date_locked(
            target_date=target_date,
            current_date=current_date,
            lock_policy=configuration.get("lock_policy"),
        )

        day_key = f"{target_date.day:02d}-{target_date.month:02d}"
        one_time_entries = [
            {**entry, "is_recurring": False}
            for entry in month_one_time.get(day_key, [])
        ]
        recurring_entries = month_recurring.get(target_date.day, [])

        return {
            "iso_date": target_date.isoformat(),
            "year": target_date.year,
            "month": target_date.month,
            "day": target_date.day,
            "is_locked": is_locked,
            "daily_average": daily_average,
            "remaining_budget": month_summary["remaining_budget"],
            "items": one_time_entries + recurring_entries,
        }