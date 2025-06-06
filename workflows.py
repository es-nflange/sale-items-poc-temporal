import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional


from temporalio import workflow
from temporalio.exceptions import ApplicationError

from activities import post_update_activity
from models import SaleItem

with workflow.unsafe.imports_passed_through():
    from activities import (
        move_from_open_to_ready,
        move_from_ready_to_open,
        move_from_ready_to_billed_pending,
        move_from_billed_pending_to_billed_approved,
    )


class StateMachine:
    def __init__(self, initial_state, transitions):
        self.state = initial_state
        self.transitions = transitions

    def can_transition(self, new_state):
        return new_state in self.transitions.get(self.state, [])

    def transition(self, new_state):
        if self.can_transition(new_state):
            self.state = new_state
        else:
            raise ValueError(f"Invalid transition from {self.state} to {new_state}")


transitions = {
    "open": ["ready"],
    "ready": ["open", "billed_pending"],
    "billed_pending": ["billed_approved"],
    "billed_approved": ["billed_pending"],
}


@dataclass
class SaleItemStatusUpdateInput:
    status: str


@dataclass
class SaleItemSplitInput:
    quantity: int


@dataclass
class MarkFulfilledInput:
    name: str


@dataclass
class SaleItemWorkflowInput:
    sale_item_id: str
    quantity: int
    status: Optional[str] = None


@workflow.defn
class SaleItemWorkflow:

    def __init__(self) -> None:
        self.lock = asyncio.Lock()  # used by the async handler below
        self.should_update = False  # used by the async handler below
        self.sale_item_fulfilled = False
        self.sale_item: Optional[SaleItem] = None

    @workflow.run
    async def run(self, input: SaleItemWorkflowInput) -> dict:
        # 👉 In addition to waiting for the `sale_item_fulfilled` Signal, we also wait for
        # all handlers to finish. Otherwise, the Workflow might return its
        # result while an async set_language_using_activity Update is in
        # progress.
        self.sale_item = SaleItem(
            sale_item_id=input.sale_item_id,
            current_status=input.status or "open",
            quantity=input.quantity,
        )
        workflow.logger.info(
            f"Workflow started with sale item ID: {self.sale_item.sale_item_id} and status: {self.sale_item.current_status}"
        )
        self.should_update = False
        await workflow.wait_condition(
            lambda: (self.should_update or self.sale_item_fulfilled)
            and workflow.all_handlers_finished()
        )
        if self.should_update:
            workflow.logger.info(
                "Workflow update requested, continuing as new with updated sale item"
            )
            workflow.continue_as_new(
                SaleItemWorkflowInput(
                    sale_item_id=self.sale_item.sale_item_id,
                    quantity=self.sale_item.quantity,
                    status=self.sale_item.current_status,
                )
            )
        return {}

    @workflow.signal
    def mark_fulfilled(self, input: MarkFulfilledInput) -> None:
        # 👉 A Signal handler mutates the Workflow state but cannot return a value.
        self.sale_item_fulfilled = True
        self.approver_name = input.name

    @workflow.update
    async def update_status(self, input: SaleItemStatusUpdateInput) -> SaleItem:
        if self.sale_item is None:
            raise ApplicationError("Sale item not initialized")
        current_status = self.sale_item.current_status
        new_status = input.status
        workflow.logger.info(
            f"Updating status from {current_status} to {new_status} for sale item ID: {self.sale_item.sale_item_id}"
        )

        self._check_status_transition(current_status, new_status)

        match new_status:
            case "open":
                workflow.logger.info(
                    f"Transitioning sale item {self.sale_item.sale_item_id} to OPEN status"
                )
                await workflow.execute_activity(
                    move_from_ready_to_open,
                    self.sale_item,
                    start_to_close_timeout=timedelta(seconds=10),
                )

            case "ready":
                workflow.logger.info(
                    f"Transitioning sale item {self.sale_item.sale_item_id} to READY status"
                )
                await workflow.execute_activity(
                    move_from_open_to_ready,
                    self.sale_item,
                    start_to_close_timeout=timedelta(seconds=10),
                )

            case "billed_pending":
                workflow.logger.info(
                    f"Transitioning sale item {self.sale_item.sale_item_id} to BILLED_PENDING status"
                )
                await workflow.execute_activity(
                    move_from_ready_to_billed_pending,
                    self.sale_item,
                    start_to_close_timeout=timedelta(seconds=10),
                )

            case "billed_approved":
                workflow.logger.info(
                    f"Transitioning sale item {self.sale_item.sale_item_id} to BILLED_APPROVED status"
                )
                await workflow.execute_activity(
                    move_from_billed_pending_to_billed_approved,
                    self.sale_item,
                    start_to_close_timeout=timedelta(seconds=10),
                )
                self.sale_item_fulfilled = True

            case _:
                raise ApplicationError(f"Invalid status: {new_status}")

        # Incorrect
        # await workflow.execute_activity(
        #     post_update_activity,
        #     self.sale_item,
        #     start_to_close_timeout=timedelta(seconds=10),
        # )

        # Correct
        # is_patched = workflow.patched("post_update_activity")
        # if is_patched:
        #     workflow.logger.info(
        #         f"Post-update activity patched for sale item {self.sale_item.sale_item_id}"
        #     )
        #     await workflow.execute_activity(
        #         post_update_activity,
        #         self.sale_item,
        #         start_to_close_timeout=timedelta(seconds=10),
        #     )
        # else:
        #     workflow.logger.warning(
        #         "post_update_activity is not patched, skipping post-update activity"
        #     )

        self.sale_item.current_status = new_status
        workflow.logger.info(
            f"Status updated to {self.sale_item.current_status} for sale item ID: {self.sale_item.sale_item_id}"
        )
        return self.sale_item

    def _check_status_transition(self, current_status: str, new_status: str) -> None:
        state_machine = StateMachine(current_status, transitions)
        try:
            state_machine.transition(new_status)
        except ValueError as e:
            raise ApplicationError(
                f"Invalid status transition from {current_status} to {new_status}: {e}"
            )

    @workflow.update
    async def split_sale_item(self, input: SaleItemSplitInput) -> dict:
        quantity = input.quantity
        if self.sale_item is None:
            raise ApplicationError("Sale item not initialized")
        async with self.lock:
            if self.sale_item.quantity is None or self.sale_item.quantity < quantity:
                raise ApplicationError("Not enough quantity to split sale item")

            new_sale_item = SaleItem(
                sale_item_id="89101112", current_status="open", quantity=quantity
            )
            self.sale_item.quantity -= quantity
            workflow.logger.info(
                f"Sale item split: {new_sale_item} remaining quantity: {self.sale_item.quantity}"
            )

            return await workflow.execute_child_workflow(
                SaleItemWorkflow.run,
                SaleItemWorkflowInput(
                    sale_item_id=new_sale_item.sale_item_id,
                    quantity=new_sale_item.quantity,
                ),
                id=f"sale-item-poc-workflow-{new_sale_item.sale_item_id}",
                task_queue="sale_item_poc_task_queue",
            )

    @workflow.query
    def get_sale_item(self) -> SaleItem:
        if self.sale_item is None:
            raise ApplicationError("Sale item not initialized")
        return self.sale_item

    @workflow.query
    def get_transitions(self) -> dict:
        return transitions

    @workflow.update
    def update_workflow(self):
        self.should_update = True
