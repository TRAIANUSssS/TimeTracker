"""Validate generations and sequence continuity before handing records to a caller."""


class EventStream:
    def __init__(self):
        self.stream_id = None
        self.message_sequence = 0
        self.record_sequence = 0
        self.gap = False
        self.healthy = False
        self.stopped = False

    def accept(self, message):
        try:
            return self._accept(message)
        except (ValueError, RuntimeError, TypeError, AttributeError):
            self.healthy = False
            self.gap = True
            raise

    def _accept(self, message):
        if message.get("schema_version") != 1:
            raise ValueError("Unsupported event protocol")
        if message.get("type") == "error":
            self.healthy = False
            raise RuntimeError(message.get("error", "Collector failed"))
        kind = message.get("type")
        if kind not in ("ready", "batch", "draining", "stopped") or self.stopped:
            raise ValueError("Unexpected event message")
        if self.stream_id is None:
            if kind != "ready" or not isinstance(message.get("stream_id"), str):
                raise ValueError("Event stream must begin with ready")
            self.stream_id = message["stream_id"]
        elif message.get("stream_id") != self.stream_id or kind == "ready":
            raise ValueError("Unexpected event generation")
        sequence = message.get("message_sequence")
        if type(sequence) is not int or sequence != self.message_sequence + 1:
            raise ValueError("Event message sequence gap")
        self.message_sequence = sequence
        records = message.get("records", [])
        if not isinstance(records, list) or len(records) > 8:
            raise ValueError("Invalid event batch")
        for record in records:
            if not isinstance(record, dict) or record.get("kind") not in ("start", "stop"):
                raise ValueError("Invalid process event")
            for key in ("pid", "sequence", "generated_at_ns", "received_at_ns"):
                if type(record.get(key)) is not int or record[key] < 0:
                    raise ValueError(f"Invalid event {key}")
            if record["pid"] > 0xFFFFFFFF or record["sequence"] <= self.record_sequence:
                raise ValueError("Invalid event identity or order")
            if record["sequence"] != self.record_sequence + 1:
                self.gap = True
            self.record_sequence = record["sequence"]
            creation = record.get("creation_time_ns")
            if type(creation) is not int or creation < 0:
                self.gap = True  # no PID-only fallback for missing identity
            if record["kind"] == "start" and not isinstance(record.get("image_name"), str):
                self.gap = True
        if kind in ("batch", "draining") and message.get("data_complete") is not True:
            self.gap = True
        self.stopped = kind == "stopped"
        self.healthy = kind == "batch" and message.get("healthy") is True and not self.gap
        return records
