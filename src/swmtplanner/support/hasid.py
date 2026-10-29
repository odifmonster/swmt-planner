class HasID[T]:
    id: T

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return False
        return self.id == other.id  # type: ignore[attr-defined]

    def __hash__(self) -> int:
        return hash(self.id)
