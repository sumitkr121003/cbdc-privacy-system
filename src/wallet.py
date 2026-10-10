
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


class Wallet:
    def __init__(self):
        # Generate a new private/public key pair
        self.private_key = Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()

    def sign_message(self, message):
        # Convert text into bytes before signing
        message_bytes = message.encode("utf-8")

        # Sign using the private key
        signature = self.private_key.sign(message_bytes)

        return signature

    def verify_signature(self, message, signature):
        # Verify using the public key
        message_bytes = message.encode("utf-8")

        try:
            self.public_key.verify(signature, message_bytes)
            return True
        except InvalidSignature:
            return False

    
    def sign_payment(self, sender, recipient, amount, fee, input_ids):
        """Sign the details of a payment."""
        message = self.create_payment_message(
            sender, recipient, amount, fee, input_ids
        )
        return self.sign_message(message)

    @staticmethod
    def create_payment_message(sender, recipient, amount, fee, input_ids):
        """Create a consistent message for signing and verification."""
        import json

        payment_data = {
            "sender": sender,
            "recipient": recipient,
            "amount": amount,
            "fee": fee,
            "input_ids": sorted(input_ids),
        }

        return json.dumps(
            payment_data,
            sort_keys=True,
            separators=(",", ":"),
        )    

    
    def get_address(self):
        """Return a wallet identifier derived from its public key."""
        return self.get_public_key_hex()    

    def get_public_key_hex(self):
        # Export the public key in hexadecimal format
        public_key_bytes = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        return public_key_bytes.hex()