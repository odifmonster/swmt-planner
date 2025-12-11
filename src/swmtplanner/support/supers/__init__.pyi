from .viewer import setter_like, Viewer

__all__ = ['setter_like', 'SwmtBase', 'Viewer']

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
            accessible. Instances must have corresponding "private"
            attributes with a preceding '_'.
        """
        ...
    def __init__(self, **kwargs) -> None:
        """
        Initialize a new SwmtBase object. Should not be called
        directly.

          **kwargs:
            Every keyword will become an attribute of the instance,
            and the value will be used as the initial value. If any
            names provided to the initializer are not present as
            keywords (preceded by '_'), a ValueError is raised. If
            any keyword is the name of a read-only attribute, a
            ValueError is raised.
        """
        ...