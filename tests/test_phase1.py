import threading
from dataclasses import FrozenInstanceError
import pytest

from src.utxo_engine import UTXO, Transaction, TransactionResult, UTXOEngine
from src.wallet import Wallet


def test_transaction_dataclass_instantiation_and_immutability():
    """Verify Transaction dataclass instantiation and frozen immutability."""
    tx = Transaction(
        sender="Alice",
        recipient="Bob",
        amount=10,
        fee=1,
        input_ids=("genesis-Alice-1",),
        signature=b"test_signature_bytes",
        tx_id=1,
    )

    assert tx.sender == "Alice"
    assert tx.recipient == "Bob"
    assert tx.amount == 10
    assert tx.fee == 1
    assert tx.input_ids == ("genesis-Alice-1",)
    assert tx.signature == b"test_signature_bytes"
    assert tx.tx_id == 1

    with pytest.raises(FrozenInstanceError):
        tx.amount = 20


def test_transaction_result_dataclass_instantiation_and_immutability():
    """Verify TransactionResult dataclass fields and frozen immutability."""
    result = TransactionResult(
        status="SUCCESS",
        tx_id=1,
        sender="Alice",
        recipient="Bob",
        amount=10,
        fee=1,
        input_ids=("genesis-Alice-1",),
        change=4,
        outputs=(
            UTXO(output_id="tx-1-out-1", owner="Bob", amount=10),
            UTXO(output_id="tx-1-out-2", owner="Alice", amount=4),
        ),
        error_message=None,
    )

    assert result.status == "SUCCESS"
    assert result.tx_id == 1
    assert result.sender == "Alice"
    assert result.recipient == "Bob"
    assert result.change == 4
    assert len(result.outputs) == 2
    assert result.error_message is None

    with pytest.raises(FrozenInstanceError):
        result.status = "REJECTED"


def test_concurrent_issuance_thread_safety():
    """Verify concurrent issue_test_funds from multiple threads produces unique IDs."""
    engine = UTXOEngine()
    thread_count = 50
    amount_per_thread = 10
    created_utxos = []
    lock = threading.Lock()
    errors = []

    def worker(worker_id):
        try:
            utxo_id = engine.issue_test_funds(f"user-{worker_id}", amount_per_thread)
            with lock:
                created_utxos.append(utxo_id)
        except Exception as e:
            with lock:
                errors.append(e)

    threads = [
        threading.Thread(target=worker, args=(i,))
        for i in range(thread_count)
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(created_utxos) == thread_count
    # All created genesis IDs must be unique
    assert len(set(created_utxos)) == thread_count
    assert engine.next_genesis_id == thread_count + 1

    # Verify each user has correct balance
    for i in range(thread_count):
        assert engine.get_balance(f"user-{i}") == amount_per_thread


def test_concurrent_disjoint_transfers_thread_safety():
    """Verify concurrent transfers on disjoint inputs succeed without race conditions."""
    engine = UTXOEngine()
    tx_count = 30
    sender_utxos = []

    # Pre-fund senders
    for i in range(tx_count):
        out_id = engine.issue_test_funds(f"sender-{i}", 10)
        sender_utxos.append(out_id)

    errors = []
    results = []
    lock = threading.Lock()

    def transfer_worker(idx):
        try:
            res = engine.transfer(
                sender=f"sender-{idx}",
                recipient=f"recipient-{idx}",
                amount=5,
                fee=1,
                input_ids=[sender_utxos[idx]],
            )
            with lock:
                results.append(res)
        except Exception as e:
            with lock:
                errors.append(e)

    threads = [
        threading.Thread(target=transfer_worker, args=(i,))
        for i in range(tx_count)
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(results) == tx_count
    assert engine.total_fees == tx_count * 1
    assert engine.next_transaction_id == tx_count + 1

    # Verify all transaction IDs in history are unique
    tx_ids = [r["transaction_id"] for r in results]
    assert len(set(tx_ids)) == tx_count

    # Verify recipient and sender change balances
    for i in range(tx_count):
        assert engine.get_balance(f"recipient-{i}") == 5
        assert engine.get_balance(f"sender-{i}") == 4  # 10 - 5 - 1 = 4


def test_concurrent_read_queries_during_transfers():
    """Verify get_balance and get_transaction_history run safely alongside transfers."""
    engine = UTXOEngine()
    fund = engine.issue_test_funds("Alice", 100)

    stop_event = threading.Event()
    read_errors = []

    def reader():
        while not stop_event.is_set():
            try:
                bal = engine.get_balance("Alice")
                hist = engine.get_transaction_history()
                assert isinstance(bal, int)
                assert isinstance(hist, list)
            except Exception as e:
                read_errors.append(e)

    reader_thread = threading.Thread(target=reader)
    reader_thread.start()

    # Execute transfers from Alice to Bob
    current_input = fund
    for i in range(5):
        res = engine.transfer(
            sender="Alice",
            recipient=f"Bob-{i}",
            amount=5,
            fee=1,
            input_ids=[current_input],
        )
        # Find Alice's change output for the next transfer
        change_utxos = [o for o in res["outputs"] if o.owner == "Alice"]
        assert len(change_utxos) == 1
        current_input = change_utxos[0].output_id

    stop_event.set()
    reader_thread.join()

    assert len(read_errors) == 0
    assert engine.get_balance("Alice") == 100 - (5 * 6)  # 100 - 30 = 70
