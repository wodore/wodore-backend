from typing import Union

# from ..ref import RefDatabase, RefCreate, HutRefLink, HutRefLinkBase
from .hut_osm import HutOsm0Source

# from .hut_gipfelbuch import HutGipfelbuch0Source, HutGipfelbuch0Convert
# from .hut_osm import HutOsm0Source, HutOsm0Convert
# from .hut_sac import HutSac0Source, HutSac0Convert
# from .hut_hrs import HutHrs0Source, HutHrs0Convert


HutSourceTypes = Union[HutOsm0Source]
# HutSourceTypes = Union[HutOsm0Source, HutSac0Source, HutGipfelbuch0Source, HutHrs0Source]
