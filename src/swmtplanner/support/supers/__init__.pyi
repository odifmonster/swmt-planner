class SwmtBase:
    """
    The base class for all types in Shawmut planner tools.
    Allows for the declaration of read-only attributes and easy
    initializer syntax.
    """
    def __init_subclass__(cls,
                          read_only: tuple[str, ...] = tuple(),
                          priv: tuple[str, ...] = tuple()) -> None:
        """
        Initialize a new SwmtBase subclass.

          read_only:
            A list of read-only attributes (if any). These names
            will refer to properties without setters, and instances
            must have corresponding "private" attributes with a
            preceding '_'.
          priv:
            A list of additional attributes (if any) to be required
            for initialization that should not be publicly
            accessible. The corresponding attributes will have a
            preceding '_'.
        """
        ...
    def __init__(self, priv: dict[str] = {}, **kwargs) -> None:
        """
        Initialize a new SwmtBase object. Should not be called
        directly.

          priv: (default {})
            A mapping from private names (without a preceding '_')
            to their values. All names provided to 'read_only' and
            'priv' in the subclass initializer must be included.
          **kwargs:
            Every keyword will become an attribute of the instance,
            and the value will be used as the initial value. If any
            keyword is the name of a read-only attribute, a value
            error is raised.
        """
        ...