import pytest

from src.utxo_engine import UTXO, UTXOEngine

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
    assert engine.get_transaction_history() == []


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


def test_successful_transfer_is_saved_in_history():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    result = engine.transfer(
        "Alice", "Bob", 10, 1, [alice_utxo]
    )

    history = engine.get_transaction_history()

    assert len(history) == 1
    assert history[0]["transaction_id"] == result["transaction_id"]
    assert history[0]["sender"] == "Alice"
    assert history[0]["recipient"] == "Bob"
    assert history[0]["amount"] == 10
    assert history[0]["fee"] == 1
    assert history[0]["input_ids"] == [alice_utxo]
    assert history[0]["status"] == "SUCCESS"


def test_failed_transfer_is_not_saved_in_history():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    with pytest.raises(ValueError, match="Insufficient funds"):
        engine.transfer(
            "Alice", "Bob", 15, 1, [alice_utxo]
        )

    assert engine.get_transaction_history() == []


def test_modifying_returned_history_does_not_change_stored_history():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    engine.transfer(
        "Alice", "Bob", 10, 1, [alice_utxo]
    )

    history = engine.get_transaction_history()

    # Try modifying the returned record and its nested outputs.
    history[0]["amount"] = 999
    history[0]["outputs"].clear()
    history.clear()

    # The engine's stored history must remain unchanged.
    stored_history = engine.get_transaction_history()

    assert len(stored_history) == 1
    assert stored_history[0]["amount"] == 10
    assert len(stored_history[0]["outputs"]) == 2


def test_successful_transfers_have_unique_transaction_ids():
    engine = UTXOEngine()

    first_utxo = engine.issue_test_funds("Alice", 20)
    first_result = engine.transfer(
        "Alice", "Bob", 10, 1, [first_utxo]
    )

    # Spend Alice's change output in a second transaction.
    alice_change = engine.get_unspent_outputs("Alice")[0]
    second_result = engine.transfer(
        "Alice", "Charlie", 5, 1, [alice_change.output_id]
    )

    assert first_result["transaction_id"] == 1
    assert second_result["transaction_id"] == 2

    history = engine.get_transaction_history()
    transaction_ids = [
        transaction["transaction_id"] for transaction in history
    ]

    assert transaction_ids == [1, 2]
    assert len(transaction_ids) == len(set(transaction_ids))


def test_output_id_collision_does_not_modify_ledger():
    engine = UTXOEngine()
    engine.issue_test_funds("Alice", 100)

    original_input = next(iter(engine.get_unspent_outputs("Alice")))

    # Simulate an output ID that already exists.
    collision = UTXO(output_id="tx-1-out-1", owner="Eve", amount=7)
    engine.utxos[collision.output_id] = collision

    with pytest.raises(ValueError, match="output ID already exists"):
        engine.transfer(
            sender="Alice",
            recipient="Bob",
            amount=30,
            fee=2,
            input_ids=[original_input.output_id],
        )

    # The failed transfer must leave the ledger unchanged.
    assert engine.utxos[collision.output_id] == collision
    assert original_input.output_id not in engine.spent_utxos
    assert engine.get_balance("Alice") == 100
    assert engine.get_balance("Bob") == 0
    assert engine.total_fees == 0
    assert engine.transaction_history == []
    assert engine.next_transaction_id == 1


def test_validate_transfer_does_not_modify_ledger():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    original_balance = engine.get_balance("Alice")
    original_history = engine.get_transaction_history()
    original_transaction_id = engine.next_transaction_id
    original_fees = engine.total_fees
    original_spent = set(engine.spent_utxos)

    result = engine.validate_transfer(
        sender="Alice",
        recipient="Bob",
        amount=10,
        fee=1,
        input_ids=[alice_utxo],
    )

    assert result is True
    assert engine.get_balance("Alice") == original_balance
    assert engine.get_balance("Bob") == 0
    assert engine.get_transaction_history() == original_history
    assert engine.next_transaction_id == original_transaction_id
    assert engine.total_fees == original_fees
    assert engine.spent_utxos == original_spent


def test_validate_transfer_rejects_insufficient_funds_without_changes():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 5)

    with pytest.raises(ValueError, match="Insufficient funds"):
        engine.validate_transfer(
            sender="Alice",
            recipient="Bob",
            amount=5,
            fee=1,
            input_ids=[alice_utxo],
        )

    assert engine.get_balance("Alice") == 5
    assert engine.get_balance("Bob") == 0
    assert alice_utxo not in engine.spent_utxos
    assert engine.transaction_history == []
    assert engine.total_fees == 0
    assert engine.next_transaction_id == 1


def test_validate_transfer_rejects_spent_input_without_changes():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 15)

    # Spend the input through the existing transfer method.
    engine.transfer("Alice", "Bob", 10, 1, [alice_utxo])

    balance_alice = engine.get_balance("Alice")
    balance_bob = engine.get_balance("Bob")
    history_before = engine.get_transaction_history()
    fees_before = engine.total_fees
    transaction_id_before = engine.next_transaction_id

    with pytest.raises(ValueError, match="already spent"):
        engine.validate_transfer(
            sender="Alice",
            recipient="Charlie",
            amount=5,
            fee=1,
            input_ids=[alice_utxo],
        )

    assert engine.get_balance("Alice") == balance_alice
    assert engine.get_balance("Bob") == balance_bob
    assert engine.get_balance("Charlie") == 0
    assert engine.get_transaction_history() == history_before
    assert engine.total_fees == fees_before
    assert engine.next_transaction_id == transaction_id_before


def test_validate_transfer_rejects_duplicate_inputs_without_changes():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 10)

    with pytest.raises(ValueError, match="Duplicate transaction inputs"):
        engine.validate_transfer(
            sender="Alice",
            recipient="Bob",
            amount=15,
            fee=0,
            input_ids=[alice_utxo, alice_utxo],
        )

    assert engine.get_balance("Alice") == 10
    assert engine.get_balance("Bob") == 0
    assert alice_utxo not in engine.spent_utxos
    assert engine.get_transaction_history() == []
    assert engine.total_fees == 0
    assert engine.next_transaction_id == 1


def test_validate_transfer_rejects_foreign_input_without_changes():
    engine = UTXOEngine()
    alice_utxo = engine.issue_test_funds("Alice", 10)

    with pytest.raises(ValueError, match="does not own UTXO"):
        engine.validate_transfer(
            sender="Mallory",
            recipient="Bob",
            amount=5,
            fee=1,
            input_ids=[alice_utxo],
        )

    assert engine.get_balance("Alice") == 10
    assert engine.get_balance("Mallory") == 0
    assert engine.get_balance("Bob") == 0
    assert alice_utxo not in engine.spent_utxos
    assert engine.get_transaction_history() == []
    assert engine.total_fees == 0
    assert engine.next_transaction_id == 1


def test_validate_transfer_rejects_unknown_input_without_changes():
    engine = UTXOEngine()
    engine.issue_test_funds("Alice", 10)

    with pytest.raises(ValueError, match="Unknown UTXO"):
        engine.validate_transfer(
            sender="Alice",
            recipient="Bob",
            amount=5,
            fee=1,
            input_ids=["unknown-utxo"],
        )

    assert engine.get_balance("Alice") == 10
    assert engine.get_balance("Bob") == 0
    assert engine.spent_utxos == set()
    assert engine.get_transaction_history() == []
    assert engine.total_fees == 0
    assert engine.next_transaction_id == 1
