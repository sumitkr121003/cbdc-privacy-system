import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from src.utxo_engine import UTXO, Transaction, TransactionResult, UTXOEngine
from src.wallet import Wallet


class BatchTransactionProcessor:
    """
    Two-phase transaction batch processor.

    Phase 1 (Parallel Read-Only Validation):
        Executes Ed25519 cryptographic signature verification and structural
        parameter validation concurrently across worker threads.
        Because Ed25519 verification in `cryptography` runs in C, it releases
        the Python GIL, allowing multi-core CPU utilization.

    Phase 2 (Atomic Commit & Conflict Resolution):
        Under the protection of the UTXOEngine lock, sequentially verifies
        that inputs remain unspent against the live ledger. Non-conflicting
        transactions are committed atomically. Competing transactions spending
        the same UTXO are rejected with status CONFLICT_DOUBLE_SPEND.
    """

    def __init__(self, engine: UTXOEngine):
        if engine is None or not isinstance(engine, UTXOEngine):
            raise ValueError("A valid UTXOEngine instance is required")
        self.engine = engine

    def _validate_single_transaction_read_only(
        self, tx: Transaction
    ) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Validate transaction parameters, signatures, and input availability
        in a read-only manner without mutating the ledger.

        Returns:
            (is_valid: bool, error_message: Optional[str], change: Optional[int])
        """
        # 1. Structural parameter validation
        if not tx.sender or not tx.recipient:
            return False, "Sender and recipient are required", None

        if tx.sender == tx.recipient:
            return False, "Sender and recipient must differ", None

        if type(tx.amount) is not int:
            return False, "Payment amount must be an integer", None

        if type(tx.fee) is not int:
            return False, "Fee must be an integer", None

        if tx.amount <= 0:
            return False, "Payment amount must be positive", None

        if tx.fee < 0:
            return False, "Fee cannot be negative", None

        if not tx.input_ids:
            return False, "At least one input is required", None

        if len(tx.input_ids) != len(set(tx.input_ids)):
            return False, "Duplicate transaction inputs", None

        # 2. Cryptographic signature verification (Releases GIL in C)
        if tx.signature is None:
            return False, "Payment signature is required", None

        wallet = self.engine.wallets.get(tx.sender)
        if wallet is None:
            return False, f"Sender wallet is not registered: {tx.sender}", None

        sender_address = wallet.get_address()
        canonical_message = Wallet.create_payment_message(
            sender_address, tx.recipient, tx.amount, tx.fee, list(tx.input_ids)
        )

        if not wallet.verify_signature(canonical_message, tx.signature):
            return False, "Invalid payment signature", None

        # 3. Read-only balance and state pre-check
        try:
            # We call _prepare_transfer under engine lock to safely read
            with self.engine._lock:
                sender_key = tx.sender
                if tx.sender in self.engine.wallets:
                    sender_key = self.engine.wallets[tx.sender].get_address()

                change, _ = self.engine._prepare_transfer(
                    sender=sender_key,
                    recipient=tx.recipient,
                    amount=tx.amount,
                    fee=tx.fee,
                    input_ids=list(tx.input_ids),
                )
            return True, None, change
        except ValueError as err:
            return False, str(err), None

    def process_batch(
        self, transactions: List[Transaction], workers: int = 4
    ) -> List[TransactionResult]:
        """
        Process a batch of transactions using two-phase validation.

        Args:
            transactions: Ordered list of transactions to process.
            workers: Number of worker threads for Phase 1 parallel validation.

        Returns:
            List of TransactionResult objects preserving the original input order.
        """
        if not transactions:
            return []

        worker_count = max(1, workers)
        indexed_txs = list(enumerate(transactions))

        # -------------------------------------------------------------
        # Phase 1: Parallel Read-Only Validation (Worker Threads)
        # -------------------------------------------------------------
        phase1_results: dict[int, Tuple[bool, Optional[str], Optional[int]]] = {}

        if worker_count == 1 or len(transactions) == 1:
            for idx, tx in indexed_txs:
                phase1_results[idx] = self._validate_single_transaction_read_only(tx)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_to_idx = {
                    executor.submit(
                        self._validate_single_transaction_read_only, tx
                    ): idx
                    for idx, tx in indexed_txs
                }
                for future in future_to_idx:
                    idx = future_to_idx[future]
                    phase1_results[idx] = future.result()

        # -------------------------------------------------------------
        # Phase 2: Synchronized Conflict Resolution & Atomic Commit
        # -------------------------------------------------------------
        results: List[TransactionResult] = []

        with self.engine._lock:
            for idx, tx in indexed_txs:
                is_valid, error_msg, _ = phase1_results[idx]

                if not is_valid:
                    results.append(
                        TransactionResult(
                            status="REJECTED",
                            tx_id=None,
                            sender=tx.sender,
                            recipient=tx.recipient,
                            amount=tx.amount,
                            fee=tx.fee,
                            input_ids=tuple(tx.input_ids),
                            change=None,
                            outputs=(),
                            error_message=error_msg,
                        )
                    )
                    continue

                # Conflict Detection: check if any input was already consumed
                # by an earlier transaction in this batch or earlier in the ledger
                conflict_found = False
                conflicting_input = None
                for input_id in tx.input_ids:
                    if input_id in self.engine.spent_utxos:
                        conflict_found = True
                        conflicting_input = input_id
                        break

                if conflict_found:
                    results.append(
                        TransactionResult(
                            status="CONFLICT_DOUBLE_SPEND",
                            tx_id=None,
                            sender=tx.sender,
                            recipient=tx.recipient,
                            amount=tx.amount,
                            fee=tx.fee,
                            input_ids=tuple(tx.input_ids),
                            change=None,
                            outputs=(),
                            error_message=f"UTXO already spent: {conflicting_input}",
                        )
                    )
                    continue

                # Resolve sender identity (wallet address if registered)
                sender_key = tx.sender
                if tx.sender in self.engine.wallets:
                    sender_key = self.engine.wallets[tx.sender].get_address()

                try:
                    record = self.engine.transfer(
                        sender=sender_key,
                        recipient=tx.recipient,
                        amount=tx.amount,
                        fee=tx.fee,
                        input_ids=list(tx.input_ids),
                    )

                    results.append(
                        TransactionResult(
                            status="SUCCESS",
                            tx_id=record["transaction_id"],
                            sender=tx.sender,
                            recipient=tx.recipient,
                            amount=tx.amount,
                            fee=tx.fee,
                            input_ids=tuple(tx.input_ids),
                            change=record["change"],
                            outputs=tuple(record["outputs"]),
                            error_message=None,
                        )
                    )
                except ValueError as err:
                    err_text = str(err)
                    status = (
                        "CONFLICT_DOUBLE_SPEND"
                        if "already spent" in err_text
                        else "REJECTED"
                    )
                    results.append(
                        TransactionResult(
                            status=status,
                            tx_id=None,
                            sender=tx.sender,
                            recipient=tx.recipient,
                            amount=tx.amount,
                            fee=tx.fee,
                            input_ids=tuple(tx.input_ids),
                            change=None,
                            outputs=(),
                            error_message=err_text,
                        )
                    )

        return results
