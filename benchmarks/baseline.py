import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utxo_engine import UTXOEngine


def run_benchmark(transaction_count=1000):
    engine = UTXOEngine()
    input_ids = []

    # Prepare test funds before starting the timer.
    for i in range(transaction_count):
        output_id = engine.issue_test_funds(f"sender-{i}", 2)
        input_ids.append(output_id)

    start = time.perf_counter()

    successful = 0

    for i, output_id in enumerate(input_ids):
        result = engine.transfer(
            sender=f"sender-{i}",
            recipient=f"recipient-{i}",
            amount=1,
            fee=1,
            input_ids=[output_id],
        )

        if result["status"] == "SUCCESS":
            successful += 1

    elapsed = time.perf_counter() - start
    throughput = successful / elapsed if elapsed else 0

    print(f"Transactions attempted: {transaction_count}")
    print(f"Transactions successful: {successful}")
    print(f"Execution time: {elapsed:.6f} seconds")
    print(f"Throughput: {throughput:.2f} transactions/second")

    if successful != transaction_count:
        raise RuntimeError("Benchmark correctness check failed")


if __name__ == "__main__":
    run_benchmark()
