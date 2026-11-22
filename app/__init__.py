import os
from flask import Flask
from app.repository import BudgetRepository, RecurringRepository, TransactionRepository
from app.routes import main_bp


def create_app(data_dir: str = "data") -> Flask:
    app = Flask(__name__)
    app.config["BUDGET_REPOSITORY"] = BudgetRepository(os.path.join(data_dir, "budget.json"))
    app.config["TRANSACTION_REPOSITORY"] = TransactionRepository(os.path.join(data_dir, "transactions.json"))
    app.config["RECURRING_REPOSITORY"] = RecurringRepository(os.path.join(data_dir, "recurring.json"))
    app.register_blueprint(main_bp)
    return app