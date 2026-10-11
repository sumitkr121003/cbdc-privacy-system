import threading
from typing import Optional
from dataclasses import dataclass
from copy import deepcopy
from src.wallet import Wallet


@dataclass(frozen=True)
class UTXO:
    """
    Represents one unspent transaction output.
    """
    output_id: str
    owner: str
    amount: int


@dataclass(frozen=True)
class Transaction:
    """
    Standardized immutable transaction record.
    """
    sender: str
    recipient: str
    amount: int
    fee: int
    input_ids: tuple[str, ...]
    signature: Optional[bytes] = None
    tx_id: Optional[int] = None


@dataclass(frozen=True)
class TransactionResult:
    """
    Standardized result of a transaction execution attempt.
    """
    status: str
    tx_id: Optional[int] = None
    sender: Optional[str] = None
    recipient: Optional[str] = None
    amount: Optional[int] = None
    fee: Optional[int] = None
    input_ids: tuple[str, ...] = ()
    change: Optional[int] = None
    outputs: tuple[UTXO, ...] = ()
    error_message: Optional[str] = None


class UTXOEngine:
    """
    A simple in-memory UTXO engine for educational testing.
    """


    def transfer_signed(
        self, sender, recipient, amount, fee, input_ids, signature
    ):
        """Execute a payment only if the registered wallet signs it."""
        with self._lock:
            wallet = self.wallets.get(sender)

            if wallet is None:
                raise ValueError("Sender wallet is not registered")

            if not input_ids:
                raise ValueError("At least one input is required")

            # Signatures use the wallet address, not the owner's display name.
            sender_address = wallet.get_address()

            message = Wallet.create_payment_message(
                sender_address, recipient, amount, fee, input_ids
            )

            if not wallet.verify_signature(message, signature):
                raise ValueError("Invalid payment signature")

            # Verify authorization before modifying transaction state.
            # Existing transfer() performs the UTXO and balance checks.
            return self.transfer(
                sender=sender_address,
                recipient=recipient,
                amount=amount,
                fee=fee,
                input_ids=input_ids,
            )

    def __init__(self):
        self._lock = threading.RLock()
        self.utxos = {}
        self.spent_utxos = set()
        self.next_transaction_id = 1
        self.next_genesis_id = 1
        self.total_fees = 0
        self.wallets = {}
        self.transaction_history = []

    def register_wallet(self, owner, wallet):
        """Register an owner without allowing wallet replacement."""
        with self._lock:
            if not owner:
                raise ValueError("Owner cannot be empty")

            if not isinstance(wallet, Wallet):
                raise ValueError("A valid Wallet is required")

            if owner in self.wallets:
                raise ValueError("Wallet owner is already registered")

            if any(
                existing.get_address() == wallet.get_address()
                for existing in self.wallets.values()
            ):
                raise ValueError("Wallet is already registered to another owner")

            self.wallets[owner] = wallet


    def verify_payment_signature(
        self, sender, recipient, amount, fee, input_ids, signature
    ):
        """Verify that the registered sender signed these payment details."""
        with self._lock:
            wallet = self.wallets.get(sender)

        if wallet is None:
            return False

        if wallet.get_address() != sender:
            return False

        message = Wallet.create_payment_message(
            sender, recipient, amount, fee, input_ids
        )

        return wallet.verify_signature(message, signature)


    def issue_test_funds(self, owner, amount):
        """
        Create initial test funds for a wallet.
        This is a simulator-only issuance operation.
        """
        with self._lock:
            if not owner:
                raise ValueError("Owner cannot be empty")

            if type(amount) is not int:
                raise ValueError("Amount must be an integer")

            if amount <= 0:
                raise ValueError("Amount must be positive")

            output_id = f"genesis-{owner}-{self.next_genesis_id}"
            self.next_genesis_id += 1

            if output_id in self.utxos:
                raise ValueError("Test funds already issued")

            self.utxos[output_id] = UTXO(
                output_id=output_id,
                owner=owner,
                amount=amount
            )

            return output_id


    def get_balance(self, owner):
        """
        Add up all unspent outputs belonging to a wallet.
        """
        with self._lock:
            return sum(
                utxo.amount
                for output_id, utxo in self.utxos.items()
                if utxo.owner == owner
                and output_id not in self.spent_utxos
            )

    def get_unspent_outputs(self, owner):
        """
        Return the wallet's currently spendable outputs.
        """
        with self._lock:
            return [
                utxo
                for output_id, utxo in self.utxos.items()
                if utxo.owner == owner
                and output_id not in self.spent_utxos
            ]



    def get_transaction_history(self):
        """Return a deep copy of successful transaction history."""
        with self._lock:
            return deepcopy(self.transaction_history)

    def _prepare_transfer(self, sender, recipient, amount, fee, input_ids):
        """Validate a payment and prepare its details without changing the ledger."""

        if not sender or not recipient:
            raise ValueError("Sender and recipient are required")

        if sender == recipient:
            raise ValueError("Sender and recipient must differ")

        if type(amount) is not int:
            raise ValueError("Payment amount must be an integer")

        if type(fee) is not int:
            raise ValueError("Fee must be an integer")

        if amount <= 0:
            raise ValueError("Payment amount must be positive")

        if fee < 0:
            raise ValueError("Fee cannot be negative")

        if not input_ids:
            raise ValueError("At least one input is required")

        if len(input_ids) != len(set(input_ids)):
            raise ValueError("Duplicate transaction inputs")

        selected_utxos = []

        for output_id in input_ids:
            if output_id not in self.utxos:
                raise ValueError(f"Unknown UTXO: {output_id}")

            if output_id in self.spent_utxos:
                raise ValueError(f"UTXO already spent: {output_id}")

            utxo = self.utxos[output_id]

            if utxo.owner != sender:
                raise ValueError(
                    f"{sender} does not own UTXO {output_id}"
                )

            selected_utxos.append(utxo)

        input_total = sum(utxo.amount for utxo in selected_utxos)
        required_total = amount + fee

        if input_total < required_total:
            raise ValueError("Insufficient funds")

        change = input_total - required_total
        transaction_id = self.next_transaction_id

        new_output_ids = [f"tx-{transaction_id}-out-1"]

        if change > 0:
            new_output_ids.append(f"tx-{transaction_id}-out-2")

        for output_id in new_output_ids:
            if output_id in self.utxos:
                raise ValueError(
                    f"Transaction output ID already exists: {output_id}"
                )

        return change, transaction_id

    def validate_transfer(self, sender, recipient, amount, fee, input_ids):
        """Validate a payment without modifying the ledger."""
        with self._lock:
            self._prepare_transfer(sender, recipient, amount, fee, input_ids)
            return True


    def transfer(self, sender, recipient, amount, fee, input_ids):
        """
        Validate and execute a payment using specified UTXOs.
        """
        with self._lock:
            # 1. Validate the payment and prepare its details.
            change, transaction_id = self._prepare_transfer(
                sender, recipient, amount, fee, input_ids
            )

            new_outputs = [
                UTXO(
                    output_id=f"tx-{transaction_id}-out-1",
                    owner=recipient,
                    amount=amount
                )
            ]

            if change > 0:
                new_outputs.append(
                    UTXO(
                        output_id=f"tx-{transaction_id}-out-2",
                        owner=sender,
                        amount=change
                    )
                )

            # Reject output ID collisions before changing the ledger.
            for output in new_outputs:
                if output.output_id in self.utxos:
                    raise ValueError(
                        f"Transaction output ID already exists: {output.output_id}"
                    )

            # 6. Commit the state change after validation succeeds.
            for output_id in input_ids:
                self.spent_utxos.add(output_id)

            for output in new_outputs:
                self.utxos[output.output_id] = output

            self.total_fees += fee
            self.next_transaction_id += 1

            transaction_record = {
                "transaction_id": transaction_id,
                "sender": sender,
                "recipient": recipient,
                "amount": amount,
                "fee": fee,
                "input_ids": list(input_ids),
                "change": change,
                "outputs": new_outputs,
                "status": "SUCCESS"
            }
            self.transaction_history.append(transaction_record)
            return transaction_record
