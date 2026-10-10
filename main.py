
from src.utxo_engine import UTXOEngine
from src.wallet import Wallet

engine = UTXOEngine()

# Create Alice's and Bob's wallets.
alice = Wallet()
bob = Wallet()

# Register Alice's wallet for signed-payment verification.
engine.register_wallet("Alice", alice)

# Give Alice 15 test units to her wallet address.
alice_utxo = engine.issue_test_funds(alice.get_address(), 15)

# Alice signs the exact payment details.
signature = alice.sign_payment(
    sender=alice.get_address(),
    recipient=bob.get_address(),
    amount=10,
    fee=1,
    input_ids=[alice_utxo],
)

# Execute the payment only after signature verification.
result = engine.transfer_signed(
    sender="Alice",
    recipient=bob.get_address(),
    amount=10,
    fee=1,
    input_ids=[alice_utxo],
    signature=signature,
)

print("Transaction:", result["status"])
print("Bob's balance:", engine.get_balance(bob.get_address()))
print("Alice's balance:", engine.get_balance(alice.get_address()))
print("Transaction fee:", result["fee"])
print("Total fees:", engine.total_fees)
print("Alice's unspent outputs:", engine.get_unspent_outputs(alice.get_address()))
