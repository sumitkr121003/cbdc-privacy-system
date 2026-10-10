import pytest

from src.utxo_engine import UTXOEngine

from src.wallet import Wallet


def test_tampered_signed_payment_is_rejected():
    engine = UTXOEngine()
    alice = Wallet()
    bob = Wallet()
    mallory = Wallet()

    engine.register_wallet("Alice", alice)
    alice_utxo = engine.issue_test_funds(alice.get_address(), 15)

    # Alice signs a payment to Bob.
    signature = alice.sign_payment(
        sender=alice.get_address(),
        recipient=bob.get_address(),
        amount=10,
        fee=1,
        input_ids=[alice_utxo],
    )

    # Someone attempts to change the recipient to Mallory.
    with pytest.raises(ValueError, match="Invalid payment signature"):
        engine.transfer_signed(
            sender="Alice",
            recipient=mallory.get_address(),
            amount=10,
            fee=1,
            input_ids=[alice_utxo],
            signature=signature,
        )

    # The rejected payment must not change the balances or spend the input.
    assert engine.get_balance(alice.get_address()) == 15
    assert engine.get_balance(bob.get_address()) == 0
    assert engine.get_balance(mallory.get_address()) == 0
    assert alice_utxo not in engine.spent_utxos


def test_signed_payment_succeeds():
    engine = UTXOEngine()
    alice = Wallet()
    bob = Wallet()

    engine.register_wallet("Alice", alice)

    alice_utxo = engine.issue_test_funds(alice.get_address(), 15)

    signature = alice.sign_payment(
        sender=alice.get_address(),
        recipient=bob.get_address(),
        amount=10,
        fee=1,
        input_ids=[alice_utxo],
    )

    result = engine.transfer_signed(
        sender="Alice",
        recipient=bob.get_address(),
        amount=10,
        fee=1,
        input_ids=[alice_utxo],
        signature=signature,
    )

    assert result["status"] == "SUCCESS"
    assert engine.get_balance(bob.get_address()) == 10
    assert engine.get_balance(alice.get_address()) == 4


def test_payment_and_change():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    result = engine.transfer(
        "Alice", "Bob", 10, 1, [alice_utxo]
    )

    assert result["status"] == "SUCCESS"
    assert engine.get_balance("Bob") == 10
    assert engine.get_balance("Alice") == 4
    assert engine.total_fees == 1


def test_double_spending_is_rejected():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    engine.transfer(
        "Alice", "Bob", 10, 1, [alice_utxo]
    )

    with pytest.raises(ValueError, match="already spent"):
        engine.transfer(
            "Alice", "Charlie", 5, 1, [alice_utxo]
        )



def test_insufficient_funds_are_rejected():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    original_transaction_id = engine.next_transaction_id
    original_fees = engine.total_fees

    with pytest.raises(ValueError, match="Insufficient funds"):
        engine.transfer(
            "Alice", "Bob", 15, 1, [alice_utxo]
        )

    # Balances must remain unchanged.
    assert engine.get_balance("Alice") == 15
    assert engine.get_balance("Bob") == 0

    # The original UTXO must remain unspent.
    assert alice_utxo not in engine.spent_utxos

    # Failed transactions must not update these values.
    assert engine.next_transaction_id == original_transaction_id
    assert engine.total_fees == original_fees


def test_cannot_spend_another_users_utxo():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    with pytest.raises(ValueError, match="does not own"):
        engine.transfer(
            "Bob", "Charlie", 5, 1, [alice_utxo]
        )

    assert engine.get_balance("Alice") == 15
    assert engine.get_balance("Bob") == 0


def test_duplicate_inputs_are_rejected():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    with pytest.raises(ValueError, match="Duplicate"):
        engine.transfer(
            "Alice", "Bob", 10, 1,
            [alice_utxo, alice_utxo]
        )

    assert engine.get_balance("Alice") == 15


def test_payment_can_use_multiple_utxos():
    engine = UTXOEngine()

    first = engine.issue_test_funds("Alice", 6)
    second = engine.issue_test_funds("Alice", 9)

    result = engine.transfer(
        "Alice", "Bob", 10, 1, [first, second]
    )

    assert result["status"] == "SUCCESS"
    assert engine.get_balance("Bob") == 10
    assert engine.get_balance("Alice") == 4
    assert engine.total_fees == 1

 
def test_zero_payment_is_rejected():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    with pytest.raises(ValueError, match="positive"):
        engine.transfer(
            "Alice", "Bob", 0, 1, [alice_utxo]
        )

    assert engine.get_balance("Alice") == 15
    assert engine.get_balance("Bob") == 0


def test_negative_fee_is_rejected():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    with pytest.raises(ValueError, match="Fee"):
        engine.transfer(
            "Alice", "Bob", 10, -1, [alice_utxo]
        )

    assert engine.get_balance("Alice") == 15
    assert engine.get_balance("Bob") == 0


def test_transaction_value_is_conserved():
    engine = UTXOEngine()

    first = engine.issue_test_funds("Alice", 6)
    second = engine.issue_test_funds("Alice", 9)

    result = engine.transfer(
        "Alice", "Bob", 10, 1, [first, second]
    )

    input_total = 6 + 9
    output_total = sum(
        output.amount for output in result["outputs"]
    )

    assert input_total == output_total + result["fee"]
    assert output_total == 14
    assert engine.get_balance("Bob") == 10
    assert engine.get_balance("Alice") == 4

    
def test_invalid_signature_cannot_spend_utxo():
    engine = UTXOEngine()
    alice = Wallet()
    bob = Wallet()
    mallory = Wallet()

    engine.register_wallet("Alice", alice)
    alice_utxo = engine.issue_test_funds(alice.get_address(), 15)

    # Mallory signs the payment instead of Alice.
    signature = mallory.sign_payment(
        sender=alice.get_address(),
        recipient=bob.get_address(),
        amount=10,
        fee=1,
        input_ids=[alice_utxo],
    )

    with pytest.raises(ValueError, match="Invalid payment signature"):
        engine.transfer_signed(
            sender="Alice",
            recipient=bob.get_address(),
            amount=10,
            fee=1,
            input_ids=[alice_utxo],
            signature=signature,
        )

    # Rejection must leave the ledger unchanged.
    assert engine.get_balance(alice.get_address()) == 15
    assert engine.get_balance(bob.get_address()) == 0
    assert alice_utxo not in engine.spent_utxos
    assert engine.next_transaction_id == 1
    assert engine.total_fees == 0

    
def test_registered_wallet_cannot_be_replaced_by_another_wallet():
    engine = UTXOEngine()
    alice = Wallet()
    mallory = Wallet()

    engine.register_wallet("Alice", alice)

    with pytest.raises(ValueError):
        engine.register_wallet("Alice", mallory)

    assert engine.wallets["Alice"] is alice


def test_signed_payment_rejects_tampered_payment_details():
    engine = UTXOEngine()
    alice = Wallet()
    bob = Wallet()
    mallory = Wallet()

    engine.register_wallet("Alice", alice)
    alice_utxo = engine.issue_test_funds(alice.get_address(), 20)
    extra_utxo = engine.issue_test_funds(alice.get_address(), 5)

    original_signature = alice.sign_payment(
        sender=alice.get_address(),
        recipient=bob.get_address(),
        amount=10,
        fee=1,
        input_ids=[alice_utxo],
    )

    tampered_payments = [
        (mallory.get_address(), 10, 1, [alice_utxo]),
        (bob.get_address(), 11, 1, [alice_utxo]),
        (bob.get_address(), 10, 2, [alice_utxo]),
        (bob.get_address(), 10, 1, [extra_utxo]),
    ]

    for recipient, amount, fee, input_ids in tampered_payments:
        with pytest.raises(
            ValueError, match="Invalid payment signature"
        ):
            engine.transfer_signed(
                sender="Alice",
                recipient=recipient,
                amount=amount,
                fee=fee,
                input_ids=input_ids,
                signature=original_signature,
            )

    # None of the rejected attempts should change the ledger.
    assert engine.get_balance(alice.get_address()) == 25
    assert engine.get_balance(bob.get_address()) == 0
    assert engine.get_balance(mallory.get_address()) == 0
    assert engine.spent_utxos == set()
    assert engine.next_transaction_id == 1
    assert engine.total_fees == 0


def test_same_wallet_cannot_be_registered_to_two_owners():
    engine = UTXOEngine()
    alice = Wallet()

    engine.register_wallet("Alice", alice)

    with pytest.raises(ValueError, match="already registered"):
        engine.register_wallet("Mallory", alice)

    assert engine.wallets["Alice"] is alice
    assert "Mallory" not in engine.wallets


@pytest.mark.parametrize("amount", [1.5, True, False, "10", None])
def test_invalid_payment_amount_is_rejected(amount):
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    with pytest.raises(ValueError, match="integer"):
        engine.transfer(
            "Alice", "Bob", amount, 1, [alice_utxo]
        )

    assert engine.get_balance("Alice") == 15
    assert engine.get_balance("Bob") == 0
    assert alice_utxo not in engine.spent_utxos


@pytest.mark.parametrize("fee", [1.5, True, False, "1", None])
def test_invalid_fee_is_rejected(fee):
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    with pytest.raises(ValueError, match="integer"):
        engine.transfer(
            "Alice", "Bob", 10, fee, [alice_utxo]
        )

    assert engine.get_balance("Alice") == 15
    assert engine.get_balance("Bob") == 0
    assert alice_utxo not in engine.spent_utxos


@pytest.mark.parametrize("amount", [1.5, True, False, "10", None])
def test_invalid_test_fund_amount_is_rejected(amount):
    engine = UTXOEngine()

    with pytest.raises(ValueError, match="integer"):
        engine.issue_test_funds("Alice", amount)

    assert engine.get_balance("Alice") == 0
    assert engine.next_genesis_id == 1
