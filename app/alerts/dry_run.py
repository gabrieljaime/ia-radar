class DryRunAlertChannel:
    """Print alert candidates without contacting an external channel."""

    is_dry_run = True

    async def send(self, text: str) -> str:
        print(f"WOULD_ALERT\n{text}\nEND_WOULD_ALERT", flush=True)
        return "dry-run"
