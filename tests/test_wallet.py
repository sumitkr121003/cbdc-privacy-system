
from src.wallet import Wallet


def test_valid_signature_is_accepted():
    alice = Wallet()

    message = "Alice pays Bob 10 units"
    signature = alice.sign_message(message)

    assert alice.verify_signature(message, signature) is True


def test_modified_message_is_rejected():
    alice = Wallet()

    message = "Alice pays Bob 10 units"
    signature = alice.sign_message(message)

    modified_message = "Alice pays Bob 100 units"

    assert alice.verify_signature(modified_message, signature) is False


def test_another_wallet_cannot_verify_alices_signature():
    alice = Wallet()
    bob = Wallet()

    message = "Alice pays Bob 10 units"
    signature = alice.sign_message(message)

    assert bob.verify_signature(message, signature) is False


def test_each_wallet_has_its_own_address():
    alice = Wallet()
    bob = Wallet()

    assert alice.get_address() == alice.get_public_key_hex()
    assert alice.get_address() != bob.get_address()


def test_payment_signature_is_valid():
    alice = Wallet()

    signature = alice.sign_payment(
        sender=alice.get_address(),
        recipient="Bob",
        amount=10,
        fee=1,
        input_ids=["utxo-1"],
    )

    message = Wallet.create_payment_message(
        sender=alice.get_address(),
        recipient="Bob",
        amount=10,
        fee=1,
        input_ids=["utxo-1"],
    )

    assert alice.verify_signature(message, signature) is True


def test_changed_payment_amount_invalidates_signature():
    alice = Wallet()

    signature = alice.sign_payment(
        sender=alice.get_address(),
        recipient="Bob",
        amount=10,
        fee=1,
        input_ids=["utxo-1"],
    )

    changed_message = Wallet.create_payment_message(
        sender=alice.get_address(),
        recipient="Bob",
        amount=100,
        fee=1,
        input_ids=["utxo-1"],
    )

    assert alice.verify_signature(changed_message, signature) is False        