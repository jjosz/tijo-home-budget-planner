import calendar
from datetime import date
from typing import Dict, List, Optional, Tuple


class DateResolver:
    @staticmethod
    def resolve_day(year: int, month: int, day_rule: Dict) -> int:
        base_day = day_rule.get("day", 1)
        max_days = calendar.monthrange(year, month)[1]
        if base_day <= max_days:
            return base_day

        short_days = day_rule.get("short_month_days") or {}
        fallback = short_days.get(str(max_days))
        if fallback is not None:
            return min(int(fallback), max_days)
        return max_days


class BudgetValidator:
    VALID_LOCK_MODES = {"NEVER", "LAST_DAY", "SPECIFIC_DAY"}
    VALID_TX_TYPES = {"EXPENSE", "INCOME"}

    @staticmethod
    def validate_day_rule(base_day: int, short_month_days: Dict[str, Optional[int]], label: str) -> Dict:
        if not 1 <= base_day <= 31:
            raise ValueError(f"{label}: day must be between 1 and 31.")

        required_lengths: List[int] = []
        if base_day >= 31:
            required_lengths.append(30)
        if base_day >= 30:
            required_lengths.append(29)
        if base_day >= 29:
            required_lengths.append(28)

        cleaned_short_days: Dict[str, int] = {}
        for month_len in required_lengths:
            raw_val = short_month_days.get(str(month_len))
            if raw_val is None or not (1 <= raw_val <= month_len):
                raise ValueError(
                    f"{label}: day for {month_len}-day months must be between 1 and {month_len}."
                )
            cleaned_short_days[str(month_len)] = raw_val

        return {"day": base_day, "short_month_days": cleaned_short_days}

    @staticmethod
    def validate_positive_amount(amount: float, label: str = "Amount") -> None:
        if amount <= 0:
            raise ValueError(f"{label} must be greater than zero.")

    @classmethod
    def validate_lock_policy(
        cls,
        lock_mode: str,
        lock_day: Optional[int],
        short_month_days: Dict[str, Optional[int]]
    ) -> Dict:
        if lock_mode not in cls.VALID_LOCK_MODES:
            raise ValueError("Invalid lock mode selected.")
        if lock_mode in {"NEVER", "LAST_DAY"}:
            return {"mode": lock_mode, "rule": None}
        if lock_day is None:
            raise ValueError("Lock day is required.")
        rule = cls.validate_day_rule(lock_day, short_month_days, "Lock day")
        return {"mode": lock_mode, "rule": rule}

    @classmethod
    def validate_transaction_fields(cls, title: str, amount: float, tx_type: str) -> None:
        if not title or len(title.strip()) < 2:
            raise ValueError("Title must contain at least 2 characters.")
        cls.validate_positive_amount(amount, "Amount")
        if tx_type not in cls.VALID_TX_TYPES:
            raise ValueError("Transaction type must be EXPENSE or INCOME.")


class BudgetLockCalculator:
    @staticmethod
    def is_date_locked(target_date: date, current_date: date, lock_policy: Optional[Dict]) -> bool:
        if not lock_policy or lock_policy.get("mode") == "NEVER":
            return False

        next_year = target_date.year + 1 if target_date.month == 12 else target_date.year
        next_month = 1 if target_date.month == 12 else target_date.month + 1
        max_days_next = calendar.monthrange(next_year, next_month)[1]

        if lock_policy.get("mode") == "LAST_DAY":
            effective_day = max_days_next
        else:
            effective_day = DateResolver.resolve_day(next_year, next_month, lock_policy["rule"])

        lock_deadline = date(next_year, next_month, effective_day)
        return current_date > lock_deadline


class RecurringService:
    @staticmethod
    def get_active_instances_for_month(
        recurring_definitions: List[Dict],
        year: int,
        month: int,
        today: Optional[date] = None
    ) -> Dict[int, List[Dict]]:
        current = today or date.today()
        if (year, month) > (current.year, current.month):
            return {}

        month_tag = f"{month:02d}-{year}"
        by_day: Dict[int, List[Dict]] = {}

        for rec in recurring_definitions:
            if (year, month) < (rec["start_year"], rec["start_month"]):
                continue
            if rec.get("end_year") is not None and rec.get("end_month") is not None:
                if (year, month) > (rec["end_year"], rec["end_month"]):
                    continue
            if month_tag in rec.get("skipped_months", []):
                continue

            resolved_day = DateResolver.resolve_day(year, month, rec["day_rule"])
            instance = {
                "id": rec["id"],
                "title": rec["title"],
                "description": rec.get("description", ""),
                "amount": rec["amount"],
                "type": rec["type"],
                "is_recurring": True
            }
            by_day.setdefault(resolved_day, []).append(instance)

        return by_day


class BudgetCalculator:
    @staticmethod
    def calculate_daily_average(monthly_budget: float, year: int, month: int) -> float:
        days_in_month = calendar.monthrange(year, month)[1]
        return round(monthly_budget / days_in_month, 2)

    @staticmethod
    def calculate_month_totals(
        monthly_budget: float,
        month_one_time: Dict[str, List[Dict]],
        month_recurring: Dict[int, List[Dict]]
    ) -> Dict:
        total_expenses = 0.0
        total_incomes = 0.0

        for tx_list in month_one_time.values():
            for tx in tx_list:
                if tx["type"] == "EXPENSE":
                    total_expenses += tx["amount"]
                elif tx["type"] == "INCOME":
                    total_incomes += tx["amount"]

        for rec_list in month_recurring.values():
            for rec in rec_list:
                if rec["type"] == "EXPENSE":
                    total_expenses += rec["amount"]
                elif rec["type"] == "INCOME":
                    total_incomes += rec["amount"]

        remaining_budget = round(monthly_budget + total_incomes - total_expenses, 2)
        return {
            "total_expenses": round(total_expenses, 2),
            "total_incomes": round(total_incomes, 2),
            "remaining_budget": remaining_budget
        }

    @staticmethod
    def determine_day_visuals(
        day_items: List[Dict],
        daily_average: float
    ) -> Dict:
        expenses = round(sum(i["amount"] for i in day_items if i["type"] == "EXPENSE"), 2)
        incomes = round(sum(i["amount"] for i in day_items if i["type"] == "INCOME"), 2)

        if incomes > 0:
            status_color = "green"
        elif expenses > daily_average:
            status_color = "red"
        elif expenses > 0:
            status_color = "orange"
        else:
            status_color = "neutral"

        return {
            "expenses": expenses,
            "incomes": incomes,
            "status_color": status_color
        }


class CalendarService:
    MONTH_NAMES_PL = [
        "", "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
        "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"
    ]

    @classmethod
    def build_month_view(
            cls,
            year: int,
            month: int,
            budget_data: Dict,
            month_one_time: Dict[str, List[Dict]],
            current_month_one_time: Dict[str, List[Dict]],
            recurring_definitions: List[Dict],
            today: Optional[date] = None
    ) -> Dict:
        current_date = today or date.today()
        monthly_budget = budget_data["initial_budget"]
        lock_policy = budget_data.get("lock_policy")

        daily_average = BudgetCalculator.calculate_daily_average(monthly_budget, year, month)
        month_recurring = RecurringService.get_active_instances_for_month(
            recurring_definitions, year, month, current_date
        )
        viewed_totals = BudgetCalculator.calculate_month_totals(
            monthly_budget, month_one_time, month_recurring
        )

        # Podsumowanie dla aktualnego (dzisiejszego) miesiąca
        if (year, month) == (current_date.year, current_date.month):
            current_totals = viewed_totals
        else:
            current_recurring = RecurringService.get_active_instances_for_month(
                recurring_definitions, current_date.year, current_date.month, current_date
            )
            current_totals = BudgetCalculator.calculate_month_totals(
                monthly_budget, current_month_one_time, current_recurring
            )

        raw_weeks = calendar.monthcalendar(year, month)
        weeks: List[List[Optional[Dict]]] = []

        for week in raw_weeks:
            formatted_week: List[Optional[Dict]] = []
            for day_num in week:
                if day_num == 0:
                    formatted_week.append(None)
                else:
                    cell_date = date(year, month, day_num)
                    day_key = f"{day_num:02d}-{month:02d}"
                    combined_items = month_one_time.get(day_key, []) + month_recurring.get(day_num, [])
                    visuals = BudgetCalculator.determine_day_visuals(combined_items, daily_average)

                    formatted_week.append({
                        "day": day_num,
                        "iso_date": cell_date.isoformat(),
                        "is_today": cell_date == current_date,
                        "is_locked": BudgetLockCalculator.is_date_locked(
                            cell_date, current_date, lock_policy
                        ),
                        "expenses": visuals["expenses"],
                        "incomes": visuals["incomes"],
                        "status_color": visuals["status_color"]
                    })
            weeks.append(formatted_week)

        prev_year, prev_month = cls.get_previous_month(year, month)
        next_year, next_month = cls.get_next_month(year, month)

        return {
            "year": year,
            "month": month,
            "month_label": f"{cls.MONTH_NAMES_PL[month]} {year}",
            "current_month_label": f"{cls.MONTH_NAMES_PL[current_date.month]} {current_date.year}",
            "current_month_remaining": current_totals["remaining_budget"],
            "viewed_month_remaining": viewed_totals["remaining_budget"],
            "viewed_month_expenses": viewed_totals["total_expenses"],
            "viewed_month_incomes": viewed_totals["total_incomes"],
            "daily_average": daily_average,
            "weeks": weeks,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month
        }
    @staticmethod
    def get_previous_month(year: int, month: int) -> Tuple[int, int]:
        return (year - 1, 12) if month == 1 else (year, month - 1)

    @staticmethod
    def get_next_month(year: int, month: int) -> Tuple[int, int]:
        return (year + 1, 1) if month == 12 else (year, month + 1)




class BudgetService:
    def __init__(self, budget_repo, tx_repo, recurring_repo):
        self.budget_repo = budget_repo
        self.tx_repo = tx_repo
        self.recurring_repo = recurring_repo

    def get_all_recurring(self) -> List[Dict]:
        return self.recurring_repo.get_all()

    def delete_recurring_completely(self, rec_id: str) -> None:
        today = date.today()
        self.recurring_repo.stop_or_delete_recurring(rec_id, today.year, today.month)

    def initialize_budget(
        self,
        reset_day: int,
        reset_short_days: Dict[str, Optional[int]],
        initial_budget: float,
        lock_mode: str,
        lock_day: Optional[int],
        lock_short_days: Dict[str, Optional[int]]
    ) -> None:
        reset_rule = BudgetValidator.validate_day_rule(reset_day, reset_short_days, "Reset day")
        BudgetValidator.validate_positive_amount(initial_budget, "Initial budget")
        lock_policy = BudgetValidator.validate_lock_policy(lock_mode, lock_day, lock_short_days)
        self.budget_repo.save_initial_setup(initial_budget, reset_rule, lock_policy)

    def get_day_details(self, target_date: date, today: Optional[date] = None) -> Dict:
        current_date = today or date.today()
        budget_data = self.budget_repo.get_budget_data()
        if not budget_data:
            raise ValueError("Budget is not initialized.")

        monthly_budget = budget_data["initial_budget"]
        month_one_time = self.tx_repo.get_month_transactions(target_date.year, target_date.month)
        recurring_defs = self.recurring_repo.get_all()
        month_recurring = RecurringService.get_active_instances_for_month(
            recurring_defs, target_date.year, target_date.month, current_date
        )

        totals = BudgetCalculator.calculate_month_totals(
            monthly_budget, month_one_time, month_recurring
        )
        daily_average = BudgetCalculator.calculate_daily_average(
            monthly_budget, target_date.year, target_date.month
        )
        is_locked = BudgetLockCalculator.is_date_locked(
            target_date, current_date, budget_data.get("lock_policy")
        )

        day_key = f"{target_date.day:02d}-{target_date.month:02d}"
        one_time_items = [
            {**tx, "is_recurring": False} for tx in month_one_time.get(day_key, [])
        ]
        recurring_items = month_recurring.get(target_date.day, [])

        return {
            "iso_date": target_date.isoformat(),
            "year": target_date.year,
            "month": target_date.month,
            "day": target_date.day,
            "is_locked": is_locked,
            "daily_average": daily_average,
            "remaining_budget": totals["remaining_budget"],
            "items": one_time_items + recurring_items
        }

    def _ensure_unlocked(self, target_date: date) -> None:
        budget_data = self.budget_repo.get_budget_data()
        if not budget_data:
            raise ValueError("Budget is not initialized.")
        if BudgetLockCalculator.is_date_locked(target_date, date.today(), budget_data.get("lock_policy")):
            raise PermissionError("This month is locked for editing.")

    def add_one_time_transaction(
        self, target_date: date, title: str, description: str, amount: float, tx_type: str
    ) -> None:
        self._ensure_unlocked(target_date)
        BudgetValidator.validate_transaction_fields(title, amount, tx_type)
        self.tx_repo.add_transaction(target_date, title.strip(), description.strip(), amount, tx_type)

    def update_one_time_transaction(
        self, target_date: date, tx_id: str, title: str, description: str, amount: float, tx_type: str
    ) -> None:
        self._ensure_unlocked(target_date)
        BudgetValidator.validate_transaction_fields(title, amount, tx_type)
        self.tx_repo.update_transaction(target_date, tx_id, title.strip(), description.strip(), amount, tx_type)

    def delete_one_time_transaction(self, target_date: date, tx_id: str) -> None:
        self._ensure_unlocked(target_date)
        self.tx_repo.delete_transaction(target_date, tx_id)

    def add_recurring_transaction(
        self,
        target_date: date,
        title: str,
        description: str,
        amount: float,
        tx_type: str,
        short_month_days: Dict[str, Optional[int]]
    ) -> None:
        self._ensure_unlocked(target_date)
        BudgetValidator.validate_transaction_fields(title, amount, tx_type)
        day_rule = BudgetValidator.validate_day_rule(
            target_date.day, short_month_days, "Recurring day"
        )
        self.recurring_repo.add_recurring(
            title=title.strip(),
            description=description.strip(),
            amount=amount,
            tx_type=tx_type,
            start_year=target_date.year,
            start_month=target_date.month,
            day_rule=day_rule
        )

    def update_recurring_transaction(
        self, target_date: date, rec_id: str, title: str, description: str, amount: float, tx_type: str
    ) -> None:
        self._ensure_unlocked(target_date)
        BudgetValidator.validate_transaction_fields(title, amount, tx_type)
        self.recurring_repo.update_recurring(rec_id, title.strip(), description.strip(), amount, tx_type)

    def remove_recurring_instance(self, target_date: date, rec_id: str, scope: str) -> None:
        self._ensure_unlocked(target_date)
        if scope == "MONTH_ONLY":
            self.recurring_repo.skip_month(rec_id, target_date.year, target_date.month)
        elif scope == "ENTIRE_SUBSCRIPTION":
            self.recurring_repo.stop_or_delete_recurring(rec_id, target_date.year, target_date.month)
        else:
            raise ValueError("Invalid removal scope.")

