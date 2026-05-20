from collections.abc import Mapping

from ...support import HasID


__all__ = ['Product', 'BeamSet', 'Greige', 'Fabric']


class Product(HasID[str]):
    """Abstract base for any item in the supply chain.

    Implements `HasID[str]`; the string ID is the product SKU. Carries the
    safety-stock target shared across all products. Subclasses extend with
    stage-specific attributes and behavior.
    """
    def __init__(self, sku: str, safety_tgt: float) -> None:
        """Build a Product.

        `sku` becomes the product's ID. `safety_tgt` is the safety-stock
        target; ignored for products whose production process is not
        modeled by the planner.
        """
        ...
    @property
    def id(self) -> str:
        """The product SKU."""
        ...
    @property
    def safety_tgt(self) -> float:
        """Safety-stock target for this product."""
        ...


class BeamSet(Product):
    """`Product` subclass for the output of the warping stage.

    Initialized from its SKU and safety target; all other attributes are
    parsed from the SKU.

    SKU format: `"<denier>D <yarn desc> <end count>X<beam count>"`,
    optionally suffixed with `" S/L"` for a split-lease beam set.
    """
    def __init__(self, sku: str, safety_tgt: float) -> None:
        """Parse `sku` to populate all derived attributes.

        Raises `ValueError` if `sku` does not match the BeamSet SKU format.
        """
        ...
    @property
    def denier(self) -> int:
        """Yarn denier."""
        ...
    @property
    def yarn_desc(self) -> str:
        """Yarn description."""
        ...
    @property
    def end_count(self) -> int:
        """Ends per beam."""
        ...
    @property
    def beam_count(self) -> int:
        """Number of beams in the set."""
        ...
    @property
    def is_split(self) -> bool:
        """True iff the beam set runs split lease (SKU ends in ` S/L`)."""
        ...


class Greige(Product):
    """`Product` subclass for the output of the knitting stage."""
    def __init__(
        self,
        sku: str,
        safety_tgt: float,
        family: str,
        gauge: int,
        top_bar: BeamSet,
        top_bar_pct: float,
        bottom_bar: BeamSet,
        bottom_bar_pct: float,
        roll_tgt_wt: float,
        machine_rates: Mapping[str, float],
    ) -> None:
        """Build a Greige product.

        `machine_rates` maps knitting-machine ID to the production rate
        (lb/hr) of this style on that machine. A machine ID present in the
        mapping means the style can run on that machine. The mapping is
        copied at construction; mutations to the caller's mapping cannot
        affect this Greige's state.
        """
        ...
    @property
    def family(self) -> str:
        """Greige family (indicates which pattern wheels the style uses)."""
        ...
    @property
    def gauge(self) -> int:
        """Knitting gauge."""
        ...
    @property
    def top_bar(self) -> BeamSet:
        """Beam set fed onto the top bar of the knitting machine."""
        ...
    @property
    def top_bar_pct(self) -> float:
        """Percent of the top-bar beam set consumed per pound of greige produced."""
        ...
    @property
    def bottom_bar(self) -> BeamSet:
        """Beam set fed onto the bottom bar of the knitting machine."""
        ...
    @property
    def bottom_bar_pct(self) -> float:
        """Percent of the bottom-bar beam set consumed per pound of greige produced."""
        ...
    @property
    def roll_tgt_wt(self) -> float:
        """Target weight per roll of this greige item, in pounds."""
        ...
    def can_run_on_machine(self, mchn_id: str) -> bool:
        """Whether the knitting machine with the given ID can run this style."""
        ...
    def rate_on_machine(self, mchn_id: str) -> float:
        """Production rate of this style on the given machine, in lb/hr.

        Raises `KeyError` if `mchn_id` is not a compatible machine; check
        `can_run_on_machine` first.
        """
        ...


class Fabric(Product):
    """`Product` subclass for the output of the dyeing stage.

    `style`, `dye_formula`, and `width` are parsed from the SKU. The color
    shade rating is not encoded in the SKU and is supplied separately.

    SKU format: `"FF <style>-<dye formula>-<width>"`.
    """
    def __init__(
        self,
        sku: str,
        safety_tgt: float,
        greige_style: str,
        yld: float,
        color_shade: int,
        jet_load_max: Mapping[str, float],
    ) -> None:
        """Build a Fabric product.

        Raises `ValueError` if `sku` does not match the Fabric SKU format.
        `jet_load_max` maps jet ID to the maximum pounds that can be loaded
        into that jet's ports to produce this item. A jet ID present in the
        mapping means the jet can run this item. The mapping is copied at
        construction; mutations to the caller's mapping cannot affect this
        Fabric's state.
        """
        ...
    @property
    def style(self) -> str:
        """Greige-style portion of the SKU."""
        ...
    @property
    def dye_formula(self) -> str:
        """Dye-formula portion of the SKU."""
        ...
    @property
    def width(self) -> float:
        """Width portion of the SKU, parsed as a float."""
        ...
    @property
    def greige_style(self) -> str:
        """The greige style this fabric is dyed from."""
        ...
    @property
    def yld(self) -> float:
        """Yield in yards of fabric produced per pound of greige consumed."""
        ...
    @property
    def color_shade(self) -> int:
        """Color shade rating, an integer in [0, 3]."""
        ...
    def can_run_on_jet(self, jet_id: str) -> bool:
        """Whether the dye jet with the given ID can run this item."""
        ...
    def load_max_on_jet(self, jet_id: str) -> float:
        """Maximum pounds loadable into the named jet's ports to produce this item.

        Raises `KeyError` if `jet_id` is not a compatible jet; check
        `can_run_on_jet` first.
        """
        ...
