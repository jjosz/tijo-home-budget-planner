import json
import os
import uuid
from datetime import date
from typing import Dict, List, Optional


class BaseJsonRepository:
    def __init__(self, file_path: str):
        self.file_path = file_path

    def _ensure_dir(self) -> None:
        directory = os.path.dirname(self.file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def _read_json(self, default):
        if not os.path.exists(self.file_path):
            return default
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, OSError):
            return default

    def _write_json(self, data) -> None:
        self._ensure_dir()
        with open(self.file_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)


class BudgetRepository(BaseJsonRepository):
    def __init__(self, file_path: str = "data/budget.json"):
        super().__init__(file_path)

    def get_budget_data(self) -> Optional[Dict]:
        data = self._read_json(None)
        if not isinstance(data, dict) or data.get("initial_budget") is None:
            return None
        return data

    def save_initial_setup(
        self,
        initial_budget: float,
        reset_rule: Dict,
        lock_policy: Dict
    ) -> None:
        data = {
            "initial_budget": initial_budget,
            "reset_rule": reset_rule,
            "lock_policy": lock_policy
        }
        self._write_json(data)


class TransactionRepository(BaseJsonRepository):
    def __init__(self, file_path: str = "data/transactions.json"):
        super().__init__(file_path)

    @staticmethod
    def _month_key(year: int, month: int) -> str:
        return f"{month:02d}-{year}"

    @staticmethod
    def _day_key(target_date: date) -> str:
        return f"{target_date.day:02d}-{target_date.month:02d}"

    def get_month_transactions(self, year: int, month: int) -> Dict[str, List[Dict]]:
        data = self._read_json({})
        return data.get(self._month_key(year, month), {})

    def get_day_transactions(self, target_date: date) -> List[Dict]:
        month_data = self.get_month_transactions(target_date.year, target_date.month)
        return list(month_data.get(self._day_key(target_date), []))

    def add_transaction(
        self,
        target_date: date,
        title: str,
        description: str,
        amount: float,
        tx_type: str
    ) -> Dict:
        data = self._read_json({})
        m_key = self._month_key(target_date.year, target_date.month)
        d_key = self._day_key(target_date)

        new_tx = {
            "id": f"tx_{uuid.uuid4().hex[:8]}",
            "title": title,
            "description": description,
            "amount": round(amount, 2),
            "type": tx_type
        }
        data.setdefault(m_key, {}).setdefault(d_key, []).append(new_tx)
        self._write_json(data)
        return new_tx

    def update_transaction(
        self,
        target_date: date,
        tx_id: str,
        title: str,
        description: str,
        amount: float,
        tx_type: str
    ) -> bool:
        data = self._read_json({})
        m_key = self._month_key(target_date.year, target_date.month)
        d_key = self._day_key(target_date)
        day_list = data.get(m_key, {}).get(d_key, [])

        for tx in day_list:
            if tx["id"] == tx_id:
                tx["title"] = title
                tx["description"] = description
                tx["amount"] = round(amount, 2)
                tx["type"] = tx_type
                self._write_json(data)
                return True
        return False

    def delete_transaction(self, target_date: date, tx_id: str) -> bool:
        data = self._read_json({})
        m_key = self._month_key(target_date.year, target_date.month)
        d_key = self._day_key(target_date)
        day_list = data.get(m_key, {}).get(d_key, [])

        filtered = [tx for tx in day_list if tx["id"] != tx_id]
        if len(filtered) == len(day_list):
            return False

        if filtered:
            data[m_key][d_key] = filtered
        else:
            del data[m_key][d_key]
            if not data[m_key]:
                del data[m_key]

        self._write_json(data)
        return True


class RecurringRepository(BaseJsonRepository):
    def __init__(self, file_path: str = "data/recurring.json"):
        super().__init__(file_path)

    def get_all(self) -> List[Dict]:
        return self._read_json([])

    def add_recurring(
        self,
        title: str,
        description: str,
        amount: float,
        tx_type: str,
        start_year: int,
        start_month: int,
        day_rule: Dict
    ) -> Dict:
        items = self.get_all()
        new_item = {
            "id": f"rec_{uuid.uuid4().hex[:8]}",
            "title": title,
            "description": description,
            "amount": round(amount, 2),
            "type": tx_type,
            "start_year": start_year,
            "start_month": start_month,
            "end_year": None,
            "end_month": None,
            "skipped_months": [],
            "day_rule": day_rule
        }
        items.append(new_item)
        self._write_json(items)
        return new_item

    def update_recurring(
        self,
        rec_id: str,
        title: str,
        description: str,
        amount: float,
        tx_type: str
    ) -> bool:
        items = self.get_all()
        for item in items:
            if item["id"] == rec_id:
                item["title"] = title
                item["description"] = description
                item["amount"] = round(amount, 2)
                item["type"] = tx_type
                self._write_json(items)
                return True
        return False

    def skip_month(self, rec_id: str, year: int, month: int) -> bool:
        items = self.get_all()
        month_tag = f"{month:02d}-{year}"
        for item in items:
            if item["id"] == rec_id:
                if month_tag not in item["skipped_months"]:
                    item["skipped_months"].append(month_tag)
                    self._write_json(items)
                return True
        return False

    def stop_or_delete_recurring(self, rec_id: str, from_year: int, from_month: int) -> bool:
        items = self.get_all()
        updated_items = []
        found = False

        for item in items:
            if item["id"] != rec_id:
                updated_items.append(item)
                continue

            found = True
            if (item["start_year"], item["start_month"]) >= (from_year, from_month):
                continue

            prev_year = from_year - 1 if from_month == 1 else from_year
            prev_month = 12 if from_month == 1 else from_month - 1
            item["end_year"] = prev_year
            item["end_month"] = prev_month
            updated_items.append(item)

        if found:
            self._write_json(updated_items)
        return found