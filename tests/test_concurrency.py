"""Stress tests for batch processing and thread-safe UTXO ledger access."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Thread

from src.batch_processor import BatchTransactionProcessor
from src.utxo_engine import Transaction, UTXOEngine
from src.wallet import Wallet


def _signed_transaction(wallet, sender, recipient, amount, fee, input_ids):
    """Build a batch transaction with a valid signature from its wallet."""
    signature = wallet.sign_payment(
        sender=wallet.get_address(),
        recipient=recipient,
        amount=amount,
        fee=fee,
        input_ids=input_ids,
    )
    return Transaction(
        sender=sender,
        recipient=recipient,
        amount=amount,
        fee=fee,
        input_ids=tuple(input_ids),
        signature=signature,
    )


def _assert_ledger_conservation(engine, initial_supply):
    """Check value supply, spent-input history, and transaction outputs."""
    history = engine.get_transaction_history()
    spent_inputs = [
        input_id
        for transaction in history
        for input_id in transaction["input_ids"]
    ]

    assert len(spent_inputs) == len(set(spent_inputs))
    assert set(spent_inputs) == engine.spent_utxos
    unspent_total = sum(
        output.amount
        for output_id, output in engine.utxos.items()
        if output_id not in engine.spent_utxos
    )
    assert initial_supply == unspent_total + engine.total_fees
    assert len(history) == len(engine.transaction_history)


def test_batch_processes_1000_non_conflicting_transactions():
    """Validate and commit 1,000 independent transactions without value loss."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)
    transaction_count = 1000
    initial_amount = 10
    transactions = []
    input_ids = []
    wallets = []

    for index in range(transaction_count):
        sender = f"sender-{index}"
        wallet = Wallet()
        wallets.append(wallet)
        engine.register_wallet(sender, wallet)
        input_id = engine.issue_test_funds(wallet.get_address(), initial_amount)
        input_ids.append(input_id)
        transactions.append(_signed_transaction(
            wallet, sender, f"recipient-{index}", 6, 1, [input_id]
        )
        )

    results = processor.process_batch(transactions, workers=8)

    assert len(results) == transaction_count
    assert all(result.status == "SUCCESS" for result in results)
    assert [result.tx_id for result in results] == list(
        range(1, transaction_count + 1)
    )
    assert len(engine.spent_utxos) == transaction_count
    assert engine.spent_utxos == set(input_ids)
    assert len(engine.get_transaction_history()) == transaction_count
    assert engine.total_fees == transaction_count
    for index in range(transaction_count):
        assert engine.get_balance(f"recipient-{index}") == 6
        assert engine.get_balance(wallets[index].get_address()) == 3
    _assert_ledger_conservation(engine, transaction_count * initial_amount)


def test_100_threads_racing_to_spend_one_utxo_have_one_winner():
    """Exactly one concurrent transfer may consume the shared input."""
    engine = UTXOEngine()
    competitor_count = 100
    initial_amount = 100
    shared_input = engine.issue_test_funds("shared-sender", initial_amount)
    start_gate = Barrier(competitor_count)

    def attempt_transfer(index):
        start_gate.wait(timeout=10)
        try:
            return engine.transfer(
                sender="shared-sender",
                recipient=f"competitor-{index}",
                amount=1,
                fee=1,
                input_ids=[shared_input],
            )["status"]
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=competitor_count) as executor:
        futures = [
            executor.submit(attempt_transfer, index)
            for index in range(competitor_count)
        ]
        outcomes = [future.result(timeout=30) for future in futures]

    assert outcomes.count("SUCCESS") == 1
    assert sum("already spent" in outcome for outcome in outcomes) == 99
    assert engine.spent_utxos == {shared_input}
    assert len(engine.get_transaction_history()) == 1
    assert engine.get_balance("shared-sender") == initial_amount - 2
    assert sum(
        engine.get_balance(f"competitor-{index}")
        for index in range(competitor_count)
    ) == 1
    assert engine.total_fees == 1
    _assert_ledger_conservation(engine, initial_amount)


def test_read_queries_wait_safely_while_batch_commit_holds_lock():
    """Queries started during commit complete with a consistent snapshot."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)
    transaction_count = 40
    transactions = []
    wallets = []
    for index in range(transaction_count):
        sender = f"reader-sender-{index}"
        wallet = Wallet()
        wallets.append(wallet)
        engine.register_wallet(sender, wallet)
        input_id = engine.issue_test_funds(wallet.get_address(), 5)
        transactions.append(_signed_transaction(
            wallet, sender, f"reader-recipient-{index}", 3, 1, [input_id]
        )
        )

    commit_paused = Event()
    query_attempted = Event()
    release_commit = Event()
    original_transfer = engine.transfer
    original_get_balance = engine.get_balance
    query_results = []

    def pause_after_first_commit(*args, **kwargs):
        result = original_transfer(*args, **kwargs)
        if not commit_paused.is_set():
            commit_paused.set()
            if not release_commit.wait(timeout=10):
                raise TimeoutError("Test did not release the paused batch commit")
        return result

    def signal_query_then_read(owner):
        query_attempted.set()
        return original_get_balance(owner)

    engine.transfer = pause_after_first_commit
    engine.get_balance = signal_query_then_read

    def run_query():
        query_results.append(engine.get_balance("reader-recipient-0"))

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            batch_future = executor.submit(
                processor.process_batch, transactions, 4
            )
            assert commit_paused.wait(timeout=10)
            # Start the read only after the commit lock is known to be held.
            reader = Thread(target=run_query, daemon=True)
            reader.start()
            assert query_attempted.wait(timeout=10)
            release_commit.set()
            results = batch_future.result(timeout=30)
        reader.join(timeout=10)
        assert not reader.is_alive(), "Read query deadlocked behind batch commit"
    finally:
        release_commit.set()

    assert len(results) == transaction_count
    assert all(result.status == "SUCCESS" for result in results)
    assert query_results == [3]
    assert engine.get_balance("reader-recipient-0") == 3
    assert len(engine.get_transaction_history()) == transaction_count
    _assert_ledger_conservation(engine, transaction_count * 5)


def test_mixed_batch_isolates_invalid_and_conflicting_transactions():
    """Valid entries commit while invalid and duplicate spends have no effects."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)
    valid_wallet = Wallet()
    conflict_wallet = Wallet()
    invalid_wallet = Wallet()
    engine.register_wallet("valid-sender", valid_wallet)
    engine.register_wallet("conflict-sender", conflict_wallet)
    engine.register_wallet("invalid-sender", invalid_wallet)
    valid_input = engine.issue_test_funds(valid_wallet.get_address(), 10)
    conflict_input = engine.issue_test_funds(conflict_wallet.get_address(), 10)

    transactions = [
        _signed_transaction(
            valid_wallet, "valid-sender", "valid-recipient", 5, 1, [valid_input]
        ),
        _signed_transaction(
            invalid_wallet, "invalid-sender", "invalid-recipient", 1, 0, ["missing"]
        ),
        _signed_transaction(
            conflict_wallet, "conflict-sender", "winner", 4, 1, [conflict_input]
        ),
        _signed_transaction(
            conflict_wallet, "conflict-sender", "loser", 3, 1, [conflict_input]
        ),
        _signed_transaction(
            valid_wallet, "valid-sender", "another-recipient", 1, 0, [valid_input]
        ),
    ]

    results = processor.process_batch(transactions, workers=5)

    assert [result.status for result in results] == [
        "SUCCESS",
        "REJECTED",
        "SUCCESS",
        "CONFLICT_DOUBLE_SPEND",
        "CONFLICT_DOUBLE_SPEND",
    ]
    assert "Unknown UTXO" in results[1].error_message
    assert engine.get_balance("valid-recipient") == 5
    assert engine.get_balance("another-recipient") == 0
    assert engine.get_balance("winner") == 4
    assert engine.get_balance("loser") == 0
    assert engine.spent_utxos == {valid_input, conflict_input}
    assert len(engine.get_transaction_history()) == 2
    assert engine.total_fees == 2
    _assert_ledger_conservation(engine, 20)


def test_batch_does_not_spend_outputs_created_earlier_in_same_batch():
    """Batch validation uses the pre-batch ledger; chained spends are unsupported."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)
    sender_wallet = Wallet()
    middle_wallet = Wallet()
    engine.register_wallet("chain-sender", sender_wallet)
    engine.register_wallet("middle", middle_wallet)
    original_input = engine.issue_test_funds(sender_wallet.get_address(), 10)
    first = _signed_transaction(
        sender_wallet, "chain-sender", middle_wallet.get_address(), 5, 1,
        [original_input],
    )
    # This ID is predictable from the engine's next transaction ID, but it is
    # not in the pre-batch ledger when the parallel validation stage runs.
    future_output = "tx-1-out-1"
    dependent = _signed_transaction(
        middle_wallet, "middle", "final", 3, 1, [future_output]
    )

    results = processor.process_batch([first, dependent], workers=2)

    assert [result.status for result in results] == ["SUCCESS", "REJECTED"]
    assert "Unknown UTXO" in results[1].error_message
    assert engine.get_balance(middle_wallet.get_address()) == 5
    assert engine.get_balance("final") == 0
    _assert_ledger_conservation(engine, 10)
