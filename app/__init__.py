import os
from typing import Callable, Optional
from flask import Flask
from app.repository import BudgetRepository, RecurringRepository, TransactionRepository
from app.routes import main_bp
from app.services import (
    BudgetConfigurationService,
    BudgetLockPolicyEvaluator,
    DayDetailsService,
    RecurringScheduleService,
    TransactionManagementService,
)


def _build_services(
    budget_repository: BudgetRepository,
    transaction_repository: TransactionRepository,
    recurring_repository: RecurringRepository,
    lock_evaluator: BudgetLockPolicyEvaluator,
) -> dict[str, object]:
    recurring_schedule_service = RecurringScheduleService(recurring_repository)
    return {
        "budget_configuration_service": BudgetConfigurationService(budget_repository),
        "day_details_service": DayDetailsService(
            budget_repository=budget_repository,
            transaction_repository=transaction_repository,
            recurring_schedule_service=recurring_schedule_service,
            lock_evaluator=lock_evaluator,
        ),
        "transaction_management_service": TransactionManagementService(
            budget_repository=budget_repository,
            transaction_repository=transaction_repository,
            lock_evaluator=lock_evaluator,
        ),
        "recurring_schedule_service": recurring_schedule_service,
    }


def create_app(
    data_directory: str = "data",
    lock_evaluator: Optional[BudgetLockPolicyEvaluator] = None,
    clock_provider: Optional[Callable] = None,
) -> Flask:
    application = Flask(__name__)
    resolved_lock_evaluator = lock_evaluator or BudgetLockPolicyEvaluator()

    budget_repository = BudgetRepository(os.path.join(data_directory, "budget.json"))
    transaction_repository = TransactionRepository(os.path.join(data_directory, "transactions.json"))
    recurring_repository = RecurringRepository(os.path.join(data_directory, "recurring.json"))

    application.config["BUDGET_REPOSITORY"] = budget_repository
    application.config["TRANSACTION_REPOSITORY"] = transaction_repository
    application.config["RECURRING_REPOSITORY"] = recurring_repository
    application.config["LOCK_POLICY_EVALUATOR"] = resolved_lock_evaluator

    if clock_provider is not None:
        application.config["CLOCK_PROVIDER"] = clock_provider

    services = _build_services(
        budget_repository=budget_repository,
        transaction_repository=transaction_repository,
        recurring_repository=recurring_repository,
        lock_evaluator=resolved_lock_evaluator,
    )
    application.config["APPLICATION_SERVICES"] = services

    application.register_blueprint(main_bp)
    return application