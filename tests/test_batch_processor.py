import pytest
from src.utxo_engine import Transaction, TransactionResult, UTXOEngine
from src.wallet import Wallet
from src.batch_processor import BatchTransactionProcessor


def _signed_transaction(wallet, sender, recipient, amount, fee, input_ids):
    """Build a batch transaction signed by the given registered wallet."""
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


def test_batch_processor_empty_batch():
    """Verify processing an empty batch returns an empty list."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)
    results = processor.process_batch([], workers=4)
    assert results == []


def test_batch_processor_invalid_engine():
    """Verify BatchTransactionProcessor requires a valid UTXOEngine instance."""
    with pytest.raises(ValueError, match="A valid UTXOEngine instance is required"):
        BatchTransactionProcessor(None)


def test_batch_processor_non_conflicting_signed_transactions():
    """Verify batch processor processes independent signed transactions successfully."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)

    tx_count = 10
    wallets = []
    transactions = []

    # Setup wallets and transactions
    for i in range(tx_count):
        wallet = Wallet()
        wallets.append(wallet)
        engine.register_wallet(f"Sender-{i}", wallet)
        utxo_id = engine.issue_test_funds(wallet.get_address(), 15)

        sig = wallet.sign_payment(
            sender=wallet.get_address(),
            recipient=f"Recipient-{i}",
            amount=10,
            fee=1,
            input_ids=[utxo_id],
        )

        tx = Transaction(
            sender=f"Sender-{i}",
            recipient=f"Recipient-{i}",
            amount=10,
            fee=1,
            input_ids=(utxo_id,),
            signature=sig,
        )
        transactions.append(tx)

    results = processor.process_batch(transactions, workers=4)

    assert len(results) == tx_count
    for i, res in enumerate(results):
        assert res.status == "SUCCESS"
        assert res.amount == 10
        assert res.fee == 1
        assert res.change == 4
        assert res.tx_id == i + 1
        assert engine.get_balance(f"Recipient-{i}") == 10
        assert engine.get_balance(wallets[i].get_address()) == 4

    assert engine.total_fees == tx_count * 1


def test_batch_processor_detects_concurrent_double_spend():
    """Verify that when two transactions compete for the same UTXO in a batch,
    the first commits and the second receives CONFLICT_DOUBLE_SPEND."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)

    alice = Wallet()
    engine.register_wallet("Alice", alice)
    alice_utxo = engine.issue_test_funds(alice.get_address(), 15)

    sig1 = alice.sign_payment(
        sender=alice.get_address(),
        recipient="Bob",
        amount=10,
        fee=1,
        input_ids=[alice_utxo],
    )
    tx1 = Transaction(
        sender="Alice",
        recipient="Bob",
        amount=10,
        fee=1,
        input_ids=(alice_utxo,),
        signature=sig1,
    )

    sig2 = alice.sign_payment(
        sender=alice.get_address(),
        recipient="Charlie",
        amount=8,
        fee=1,
        input_ids=[alice_utxo],
    )
    tx2 = Transaction(
        sender="Alice",
        recipient="Charlie",
        amount=8,
        fee=1,
        input_ids=(alice_utxo,),
        signature=sig2,
    )

    results = processor.process_batch([tx1, tx2], workers=2)

    assert len(results) == 2
    # tx1 was ordered first, so it succeeds
    assert results[0].status == "SUCCESS"
    assert results[0].recipient == "Bob"
    assert engine.get_balance("Bob") == 10

    # tx2 was ordered second, so it is caught as a double-spend collision
    assert results[1].status == "CONFLICT_DOUBLE_SPEND"
    assert "already spent" in results[1].error_message
    assert engine.get_balance("Charlie") == 0

    # Alice's original UTXO was spent only once
    assert engine.spent_utxos == {alice_utxo}
    # Alice balance is 4 (change from tx1: 15 - 10 - 1 = 4)
    assert engine.get_balance(alice.get_address()) == 4
    # Total fees is 1, not 2
    assert engine.total_fees == 1


def test_batch_processor_three_way_double_spend():
    """Verify 3-way double spend: exactly one succeeds and two are rejected."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)

    alice = Wallet()
    engine.register_wallet("Alice", alice)
    alice_utxo = engine.issue_test_funds(alice.get_address(), 20)

    txs = []
    for recipient in ["Bob", "Charlie", "David"]:
        sig = alice.sign_payment(
            sender=alice.get_address(),
            recipient=recipient,
            amount=5,
            fee=1,
            input_ids=[alice_utxo],
        )
        txs.append(
            Transaction(
                sender="Alice",
                recipient=recipient,
                amount=5,
                fee=1,
                input_ids=(alice_utxo,),
                signature=sig,
            )
        )

    results = processor.process_batch(txs, workers=4)

    assert len(results) == 3
    assert results[0].status == "SUCCESS"
    assert results[1].status == "CONFLICT_DOUBLE_SPEND"
    assert results[2].status == "CONFLICT_DOUBLE_SPEND"

    assert engine.get_balance("Bob") == 5
    assert engine.get_balance("Charlie") == 0
    assert engine.get_balance("David") == 0


def test_batch_processor_rejects_invalid_signature():
    """Verify that a transaction with a tampered or invalid signature is rejected."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)

    alice = Wallet()
    engine.register_wallet("Alice", alice)
    alice_utxo = engine.issue_test_funds(alice.get_address(), 15)

    # Corrupt the signature bytes
    bad_sig = b"\x00" * 64

    tx = Transaction(
        sender="Alice",
        recipient="Bob",
        amount=10,
        fee=1,
        input_ids=(alice_utxo,),
        signature=bad_sig,
    )

    results = processor.process_batch([tx], workers=2)

    assert len(results) == 1
    assert results[0].status == "REJECTED"
    assert results[0].error_message == "Invalid payment signature"

    # Ledger state remains unchanged
    assert engine.get_balance(alice.get_address()) == 15
    assert engine.get_balance("Bob") == 0
    assert alice_utxo not in engine.spent_utxos
    assert engine.transaction_history == []
    assert engine.total_fees == 0
    assert engine.next_transaction_id == 1


def test_batch_processor_rejects_missing_signature_without_side_effects():
    """Unsigned batch payments cannot consume inputs or create history."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)
    alice = Wallet()
    engine.register_wallet("Alice", alice)
    alice_utxo = engine.issue_test_funds(alice.get_address(), 15)
    tx = Transaction(
        sender="Alice",
        recipient="Bob",
        amount=10,
        fee=1,
        input_ids=(alice_utxo,),
        signature=None,
    )

    results = processor.process_batch([tx], workers=2)

    assert len(results) == 1
    assert results[0].status == "REJECTED"
    assert results[0].error_message == "Payment signature is required"
    assert engine.get_balance(alice.get_address()) == 15
    assert engine.get_balance("Bob") == 0
    assert alice_utxo not in engine.spent_utxos
    assert engine.total_fees == 0
    assert engine.next_transaction_id == 1
    assert engine.get_transaction_history() == []


def test_batch_processor_rejects_invalid_parameters():
    """Verify structural parameter errors are rejected with zero side-effects."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)

    alice = Wallet()
    engine.register_wallet("Alice", alice)
    alice_utxo = engine.issue_test_funds(alice.get_address(), 20)

    invalid_txs = [
        _signed_transaction(alice, "Alice", "Bob", -5, 1, [alice_utxo]),
        _signed_transaction(alice, "Alice", "Bob", 5, -1, [alice_utxo]),
        _signed_transaction(alice, "Alice", "Alice", 5, 1, [alice_utxo]),
        _signed_transaction(alice, "", "Bob", 5, 1, [alice_utxo]),
        _signed_transaction(alice, "Alice", "Bob", 5, 1, []),
        _signed_transaction(
            alice, "Alice", "Bob", 5, 1, [alice_utxo, alice_utxo]
        ),
    ]

    results = processor.process_batch(invalid_txs, workers=2)

    assert len(results) == len(invalid_txs)
    for res in results:
        assert res.status == "REJECTED"
        assert res.error_message is not None

    # Entire ledger remains unchanged
    assert engine.get_balance(alice.get_address()) == 20
    assert engine.get_balance("Bob") == 0
    assert alice_utxo not in engine.spent_utxos
    assert engine.transaction_history == []


def test_batch_processor_order_preservation():
    """Verify results list preserves the exact order of the input transactions."""
    engine = UTXOEngine()
    processor = BatchTransactionProcessor(engine)

    txs = []
    for i in range(15):
        wallet = Wallet()
        sender = f"user-{i}"
        recipient = f"dest-{i}"
        engine.register_wallet(sender, wallet)
        utxo_id = engine.issue_test_funds(wallet.get_address(), 10)
        txs.append(_signed_transaction(
            wallet, sender, recipient, 5, 1, [utxo_id]
        )
        )

    results = processor.process_batch(txs, workers=4)

    assert len(results) == 15
    for i, res in enumerate(results):
        assert res.sender == f"user-{i}"
        assert res.recipient == f"dest-{i}"
        assert res.status == "SUCCESS"
