import typing as T
from configparser import ConfigParser
# from functools import cached_property
from pathlib import Path

import pdfstream.io as io
from pdfstream.callbacks.datakeys import DataKeys
from pdfstream.vend.formatters import SpecialStr

SectionDict = T.Dict[str, str]
ConfigDict = T.Dict[str, SectionDict]
DEFAULT_CONFIGURE = {
    "METADATA": {
        "composition_str": "composition_str",
        "sample_name": "sample_name",
        "user_config": "user_config",
        "pyfai_calib_kwargs": "pyfai_calib_kwargs"
    },
    "ANALYSIS": {
        "detectors": "pe1, pe2 ,dexela",
        "image_fields": "pe1_image, pe2_image, dexela",
        "image_dtype": "uint32",
        "fill": False,
        "auto_mask": True,
        "alpha": 2.0,
        "edge": 20,
        "lower_thresh": 0.0,
        "upper_thresh": None,
        "npt": 3000,
        "correctSolidAngle": False,
        "polarization_factor": 0.99,
        "method": "bbox,csr,cython",
        "normalization_factor": 1.0,
        "pdfgetx": True,
        "rpoly": 1.2,
        "qmaxinst": 24.0,
        "qmax": 22.0,
        "qmin": 0.0,
        "rmin": 0.0,
        "rmax": 30.0,
        "rstep": 0.01,
        "composition": "Ni",
        "exports": 'yaml, poni, tiff, mask, csv, chi, chi_2theta, sq, fq, gr',
        "tiff_base": "~/acqsim/xpdUser/tiff_base",
        "directory": "{sample_name}",
        "file_prefix": "{sample_name}",
        "hints": None,
        "save_plots": False,
        "is_test": False
    },
    "VISUALIZATION": {
        "visualizers": 'image, masked_image, chi_2theta, chi, sq, fq, gr, gr_argmax, gr_max, chi_argmax, chi_max',
    },
    "PROXY": {
        "inbound_address": "localhost:5567",
        "outbound_address": "localhost:5568",
        "raw_data_prefix": "raw",
        "analyzed_data_prefix": "an"
    }
}


class ConfigError(Exception):
    """The error from the Config."""

    pass


class Config(ConfigParser):
    """The configuration for analysis callbacks."""

    def __init__(self, *args, **kwargs):
        super(Config, self).__init__(*args, **kwargs, allow_no_value=True)
        self.read_dict(DEFAULT_CONFIGURE)

    def getlist(self, section: str, option: str) -> T.List[str]:
        list_str: str = self.get(section, option)
        if not list_str:
            return list()
        return list_str.replace(" ", "").split(",")

    def getset(self, section: str, option: str) -> T.Set[str]:
        return set(self.getlist(section, option))

    @property
    def sample_name(self) -> str:
        return self.get("METADATA", "sample_name")

    @property
    def user_config(self) -> str:
        return self.get("METADATA", "user_config")

    @property
    def pyfai_calib_kwargs(self) -> str:
        return self.get("METADATA", "pyfai_calib_kwargs")

    @property
    def image_fields(self) -> T.List:
        return self.getlist("ANALYSIS", "image_fields")

    @property
    def image_dtype(self) -> str:
        return self.get("ANALYSIS", "image_dtype")

    @property
    def detectors(self) -> T.List:
        return self.getlist("ANALYSIS", "detectors")

    @property
    def fill(self) -> bool:
        return self.getboolean("ANALYSIS", "fill")

    @property
    def auto_mask(self) -> str:
        return self.getboolean("ANALYSIS", "auto_mask", fallback=True)

    @property
    def mask_setting(self) -> dict:
        return {
            "alpha": self.getfloat("ANALYSIS", "alpha"),
            "edge": self.getint("ANALYSIS", "edge"),
            "lower_thresh": self.getfloat("ANALYSIS", "lower_thresh"),
            "upper_thresh": self.get("ANALYSIS", "upper_thresh")
        }

    @property
    def integ_setting(self) -> dict:
        return {
            "npt": self.getint("ANALYSIS", "npt"),
            "correctSolidAngle": self.getboolean("ANALYSIS", "correctSolidAngle"),
            "polarization_factor": self.getfloat("ANALYSIS", "polarization_factor"),
            "method": self.get("ANALYSIS", "method"),
            "normalization_factor": self.getfloat("ANALYSIS", "normalization_factor"),
            "unit": "2th_deg"
        }

    @property
    def trans_setting(self) -> dict:
        return {
            "rpoly": self.getfloat("ANALYSIS", "rpoly"),
            "qmaxinst": self.getfloat("ANALYSIS", "qmaxinst"),
            "qmin": self.getfloat("ANALYSIS", "qmin"),
            "qmax": self.getfloat("ANALYSIS", "qmax"),
            "rmin": self.getfloat("ANALYSIS", "rmin"),
            "rmax": self.getfloat("ANALYSIS", "rmax"),
            "rstep": self.getfloat("ANALYSIS", "rstep"),
            "composition": self.get("ANALYSIS", "composition"),
            "dataformat": "QA"
        }

    @property
    def pdfgetx(self) -> bool:
        return self.getboolean("ANALYSIS", "pdfgetx")

    @property
    def exports(self) -> set:
        return self.getset("ANALYSIS", "exports")

    @property
    def tiff_base(self) -> Path:
        return Path(self.get("ANALYSIS", "tiff_base")).expanduser()

    @property
    def directory(self) -> SpecialStr:
        return SpecialStr(self.get("ANALYSIS", "directory"))

    @property
    def file_prefix(self) -> SpecialStr:
        return SpecialStr(self.get("ANALYSIS", "file_prefix"))

    @property
    def hints(self) -> T.List[str]:
        return self.getlist("ANALYSIS", "hints")

    @property
    def save_plots(self) -> bool:
        return self.getboolean("ANALYSIS", "save_plots")

    @property
    def is_test(self) -> bool:
        return self.getboolean("ANALYSIS", "is_test")

    @property
    def tiff_setting(self) -> dict:
        return {
            "astype": self.get("ANALYSIS", "tiff_astype", fallback="float32"),
            "bigtiff": self.getboolean("ANALYSIS", "tiff_bigtiff", fallback=False),
            "byteorder": self.get("ANALYSIS", "tiff_byteorder", fallback=None),
            "imagej": self.get("ANALYSIS", "tiff_imagej", fallback=False)
        }

    @property
    def visualizers(self) -> set:
        return self.getset("VISUALIZATION", "visualizers")

    @property
    def inbound_address(self):
        return self.get("PROXY", "inbound_address")

    @property
    def outbound_address(self):
        return self.get("PROXY", "outbound_address")

    @property
    def raw_data_prefix(self):
        return self.get("PROXY", "raw_data_prefix").encode()

    @property
    def analyzed_data_prefix(self):
        return self.get("PROXY", "analyzed_data_prefix").encode()

    @property
    def datakeys_list(self) -> T.List[DataKeys]:
        return [DataKeys(det, img) for det, img in zip(self.detectors, self.image_fields)]

    def to_dict(self) -> ConfigDict:
        """Convert the configuration to a dictionary."""
        return {s: dict(self.items(s)) for s in self.sections()}

    def set_analysis_config(self, section: dict) -> None:
        self.read_dict({"ANALYSIS": section})
        return

    def read_user_config(self, doc: dict) -> None:
        """Read the user configuration from the start document. It only changes the ANALSIS section."""
        key = self.get("METADATA", "user_config")
        section = doc.get(key, {})
        self.set_analysis_config(section)
        return

    def read_composition(self, doc: dict) -> None:
        """Read composition string from the start docment."""
        key = self.get("METADATA", "composition_str")
        if key in doc:
            composition = str(doc[key])
            self.set("ANALYSIS", "composition", composition)
            io.server_message("Sample composition is '{}'.".format(composition))
        else:
            io.server_message("No '{}' in the start document.".format(key))
        return

    def read_a_file(self, filename: str) -> None:
        filename = str(Path(filename))
        read_ok = self.read([filename])
        if not read_ok:
            raise ConfigError("Cannot read '{}'.".format(filename))
        return
