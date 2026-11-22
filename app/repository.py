import json
import os
import uuid
from datetime import date
from typing import Any, Dict, List, Optional


class JsonFileRepository:
    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    def _ensure_parent_directory(self) -> None:
        parent_directory = os.path.dirname(self.file_path)
        if parent_directory:
            os.makedirs(parent_directory, exist_ok=True)

    def _read_data(self, default_value: Any) -> Any:
        if not os.path.exists(self.file_path):
            return default_value
        try:
            with open(self.file_path, "r", encoding="utf-8") as file_handle:
                return json.load(file_handle)
        except (json.JSONDecodeError, OSError):
            return default_value

    def _write_data(self, payload: Any) -> None:
        self._ensure_parent_directory()
        with open(self.file_path, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, indent=2, ensure_ascii=False)


class BudgetRepository(JsonFileRepository):
    def __init__(self, file_path: str = "data/budget.json") -> None:
        super().__init__(file_path)

    def get_budget_configuration(self) -> Optional[Dict[str, Any]]:
        data = self._read_data(None)
        if not isinstance(data, dict) or data.get("initial_budget") is None:
            return None
        return data

    def save_budget_configuration(
        self,
        initial_budget: float,
        reset_rule: Dict[str, Any],
        lock_policy: Dict[str, Any],
    ) -> None:
        configuration = {
            "initial_budget": round(initial_budget, 2),
            "reset_rule": reset_rule,
            "lock_policy": lock_policy,
        }
        self._write_data(configuration)


class TransactionRepository(JsonFileRepository):
    def __init__(self, file_path: str = "data/transactions.json") -> None:
        super().__init__(file_path)

    @staticmethod
    def _build_month_key(year: int, month: int) -> str:
        return f"{month:02d}-{year}"

    @staticmethod
    def _build_day_key(target_date: date) -> str:
        return f"{target_date.day:02d}-{target_date.month:02d}"

    def get_month_transactions(self, year: int, month: int) -> Dict[str, List[Dict[str, Any]]]:
        data = self._read_data({})
        if not isinstance(data, dict):
            return {}
        month_bucket = data.get(self._build_month_key(year, month), {})
        return month_bucket if isinstance(month_bucket, dict) else {}

    def add_transaction(
        self,
        target_date: date,
        title: str,
        description: str,
        amount: float,
        transaction_type: str,
    ) -> Dict[str, Any]:
        data = self._read_data({})
        if not isinstance(data, dict):
            data = {}

        month_key = self._build_month_key(target_date.year, target_date.month)
        day_key = self._build_day_key(target_date)

        created_transaction = {
            "id": f"tx_{uuid.uuid4().hex[:8]}",
            "title": title,
            "description": description,
            "amount": round(amount, 2),
            "type": transaction_type,
        }
        data.setdefault(month_key, {}).setdefault(day_key, []).append(created_transaction)
        self._write_data(data)
        return created_transaction

    def update_transaction(
        self,
        target_date: date,
        transaction_id: str,
        title: str,
        description: str,
        amount: float,
        transaction_type: str,
    ) -> bool:
        data = self._read_data({})
        month_key = self._build_month_key(target_date.year, target_date.month)
        day_key = self._build_day_key(target_date)
        day_transactions = data.get(month_key, {}).get(day_key, [])

        for transaction in day_transactions:
            if transaction.get("id") == transaction_id:
                transaction["title"] = title
                transaction["description"] = description
                transaction["amount"] = round(amount, 2)
                transaction["type"] = transaction_type
                self._write_data(data)
                return True
        return False

    def delete_transaction(self, target_date: date, transaction_id: str) -> bool:
        data = self._read_data({})
        month_key = self._build_month_key(target_date.year, target_date.month)
        day_key = self._build_day_key(target_date)
        day_transactions = data.get(month_key, {}).get(day_key, [])

        remaining_transactions = [
            tx for tx in day_transactions if tx.get("id") != transaction_id
        ]
        if len(remaining_transactions) == len(day_transactions):
            return False

        self._store_updated_day_transactions(data, month_key, day_key, remaining_transactions)
        self._write_data(data)
        return True

    @staticmethod
    def _store_updated_day_transactions(
        data: Dict[str, Any],
        month_key: str,
        day_key: str,
        remaining_transactions: List[Dict[str, Any]],
    ) -> None:
        if remaining_transactions:
            data[month_key][day_key] = remaining_transactions
            return

        del data[month_key][day_key]
        if not data[month_key]:
            del data[month_key]


class RecurringRepository(JsonFileRepository):
    def __init__(self, file_path: str = "data/recurring.json") -> None:
        super().__init__(file_path)

    def get_all_definitions(self) -> List[Dict[str, Any]]:
        data = self._read_data([])
        return data if isinstance(data, list) else []

    def add_definition(
        self,
        title: str,
        description: str,
        amount: float,
        transaction_type: str,
        start_year: int,
        start_month: int,
        day_rule: Dict[str, Any],
    ) -> Dict[str, Any]:
        definitions = self.get_all_definitions()
        new_definition = {
            "id": f"rec_{uuid.uuid4().hex[:8]}",
            "title": title,
            "description": description,
            "amount": round(amount, 2),
            "type": transaction_type,
            "start_year": start_year,
            "start_month": start_month,
            "end_year": None,
            "end_month": None,
            "skipped_months": [],
            "day_rule": day_rule,
        }
        definitions.append(new_definition)
        self._write_data(definitions)
        return new_definition

    def update_definition(
        self,
        recurring_id: str,
        title: str,
        description: str,
        amount: float,
        transaction_type: str,
    ) -> bool:
        definitions = self.get_all_definitions()
        for definition in definitions:
            if definition.get("id") == recurring_id:
                definition["title"] = title
                definition["description"] = description
                definition["amount"] = round(amount, 2)
                definition["type"] = transaction_type
                self._write_data(definitions)
                return True
        return False

    def skip_month(self, recurring_id: str, year: int, month: int) -> bool:
        definitions = self.get_all_definitions()
        month_tag = f"{month:02d}-{year}"
        for definition in definitions:
            if definition.get("id") == recurring_id:
                skipped = definition.setdefault("skipped_months", [])
                if month_tag not in skipped:
                    skipped.append(month_tag)
                    self._write_data(definitions)
                return True
        return False

    def stop_or_remove_definition(
        self,
        recurring_id: str,
        effective_year: int,
        effective_month: int,
    ) -> bool:
        definitions = self.get_all_definitions()
        updated_definitions: List[Dict[str, Any]] = []
        found = False

        for definition in definitions:
            if definition.get("id") != recurring_id:
                updated_definitions.append(definition)
                continue

            found = True
            started_at = (definition["start_year"], definition["start_month"])
            if started_at >= (effective_year, effective_month):
                continue

            previous_year = effective_year - 1 if effective_month == 1 else effective_year
            previous_month = 12 if effective_month == 1 else effective_month - 1
            definition["end_year"] = previous_year
            definition["end_month"] = previous_month
            updated_definitions.append(definition)

        if found:
            self._write_data(updated_definitions)
        return found