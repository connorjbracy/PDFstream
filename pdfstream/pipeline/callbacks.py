import event_model
import itertools
import numpy as np
import time
from bluesky.callbacks import CallbackBase
from databroker import catalog

import pdfstream.io as io
import pdfstream.pipeline.from_descriptor as fd
import pdfstream.pipeline.from_event as fe
import pdfstream.pipeline.from_start as fs
import pdfstream.pipeline.units as units
from pdfstream.integration.tools import bg_sub, auto_mask, integrate
from .errors import ValueNotFoundError

try:
    from diffpy.pdfgetx import PDFConfig, PDFGetter
except ImportError:
    pass


class StripDepVar(CallbackBase):
    """Strip the dependent variables from a data stream. This creates a
    stream with only the independent variables, allowing the stream to be
    merged with other dependent variables (including analyzed data)"""

    def __init__(self):
        super().__init__()
        self.independent_vars = set()

    def start(self, doc):
        self.independent_vars = set(
            itertools.chain.from_iterable(
                [n for n, s in doc.get("hints", {}).get("dimensions", [])]
            )
        )

    def descriptor(self, doc):
        new_doc = dict(doc)

        # Step 1 determine which configuration and object keys to keep
        throw_out_keys = set()
        for k, v in new_doc["object_keys"].items():
            # If they share any keys then keep this component, it serves up
            # independent vars
            if not self.independent_vars & set(v):
                throw_out_keys.add(k)

        for k in ["hints", "configuration", "object_keys"]:
            new_doc[k] = dict(doc[k])
            for key in throw_out_keys:
                new_doc[k].pop(key, None)

        for k in self.independent_vars ^ set(new_doc["data_keys"]):
            new_doc["data_keys"].pop(k, None)
        return new_doc

    def event(self, doc):
        # make copies
        new_doc = dict(doc)
        new_doc["data"] = dict(doc["data"])
        new_doc["timestamps"] = dict(doc["timestamps"])
        data_keys = set(new_doc["data"].keys())
        # all the things not in
        for key in self.independent_vars ^ data_keys:
            new_doc["data"].pop(key, None)
            new_doc["timestamps"].pop(key, None)
            new_doc.get("filled", {}).pop(key, None)
        return new_doc


class DarkSubtraction(CallbackBase):
    """Dark frame subtraction callback.

    Find the dark frame in the database and subtract the image in event by the data frame. If there is no
    database specified or there is no dark id in start document, output the the same image as input. If
    dark frame is not found in database, error will be reported. The output data key is 'dk_sub_img'.
    """

    def __init__(self, img_name: str = None, *, db_name: str = None, dk_id_key: str = None):
        """Initiate the instance.

        Parameters
        ----------
        img_name :
            The data key of the image detector. If None, find one data array inside the data.

        db_name :
            The name of the intake catalog. The dark frame should be inside it.

        dk_id_key :
            The key for the id of the dark frame run.
        """
        super().__init__()
        self.img_name = img_name
        self.db = catalog[db_name] if db_name else None
        self.dk_id_key = dk_id_key

    def start(self, doc):
        metadata = fs.strip_basics(doc)
        metadata["hints"] = {}
        self.crb = event_model.compose_run(metadata=metadata)
        self.start_doc = doc
        return self.crb.start_doc

    def descriptor(self, doc):
        if not self.img_name:
            self.img_name = fd.find_one_array(doc["data_keys"])
        self.dk_img = fs.query_dk_img(self.start_doc, self.img_name, self.db, self.dk_id_key)
        self.cdb: event_model.ComposeDescriptorBundle = self.crb.compose_descriptor(
            name="primary",
            data_keys={"dk_sub_img": {"dtype": "array", "shape": [], "source": DarkSubtraction.__name__}}
        )
        return self.cdb.descriptor_doc

    def event(self, doc):
        img = fe.get_image_from_event(doc, self.img_name)
        if self.dk_img is not None:
            dk_sub_img = bg_sub(img, self.dk_img, bg_scale=1.)
        else:
            dk_sub_img = img
        return self.cdb.compose_event(
            data={"dk_sub_img": dk_sub_img},
            timestamps={"dk_sub_img": time.time()},
            filled={"dk_sub_img": "yes"}
        )

    def stop(self, doc):
        return self.crb.compose_stop()


class AutoMasking(CallbackBase):
    """Automated Masking callback.

    The mask will be generated and applied to the image. The data is a masked numpy array and its key is
    'masked_img'. The calibration metadata is required in the start document to start the auto masking.
    """

    def __init__(self, img_name: str = None, *, calibration_md_key: str, mask_setting: dict,
                 mask_config_key: str = "mask_config"):
        super().__init__()
        self.img_name = img_name
        self.calibration_md_key = calibration_md_key
        self.mask_setting = mask_setting
        self.mask_config_key = mask_config_key

    def start(self, doc):
        metadata = fs.strip_basics(doc)
        metadata[self.mask_config_key] = self.mask_setting
        metadata["hints"] = {}
        self.crb = event_model.compose_run(metadata=metadata)
        self.calibration_md = doc.get(self.calibration_md_key)
        return self.crb.start_doc

    def descriptor(self, doc):
        if not self.img_name:
            self.img_name = fd.find_one_array(doc["data_keys"])
        self.cdb: event_model.ComposeDescriptorBundle = self.crb.compose_descriptor(
            name="primary",
            data_keys={"masked_img": {"dtype": "array", "shape": [], "source": AutoMasking.__name__}}
        )
        return self.cdb.descriptor_doc

    def event(self, doc):
        img = fe.get_image_from_event(doc, self.img_name)
        if self.calibration_md:
            ai = io.load_ai_from_calib_result(self.calibration_md)
            mask, _ = auto_mask(img, ai, mask_setting=self.mask_setting)
            masked_img = np.ma.masked_array(img, mask)
        else:
            masked_img = np.ma.masked_array(img)
        return self.cdb.compose_event(
            data={"masked_img": masked_img},
            timestamps={"masked_img": time.time()},
            filled={"masked_img": "yes"}
        )

    def stop(self, doc):
        return self.crb.compose_stop()


class AzimuthalIntegration(CallbackBase):
    """Integrate the image data along azimuthal direction.

    The image will be integrated by pyFAI. The setting follows the pyFAI convention. The calibration metadata
    is required in the start document. The integration configuration will be record in the start document.
    """

    def __init__(self, img_name: str = None, *, calibration_md_key: str, integ_setting: dict, pyfai_unit: str,
                 integ_config_key: str = "integ_config"):
        """Initiate the instance.

        Parameters
        ----------
        img_name :
            The data key of the image. If None, find one data key of 2d array.

        calibration_md_key :
            The key of the calibration metadata. The metadata will be used to initiate the pyfai integrator.

        integ_setting :
            The setting of the integration. See `pyFAI.AzimuthalIntegrator.integrate1d`.

        pyfai_unit :
            The output data type. See `pyFAI.AzimuthalIntegrator.integrate1d`.

        integ_config_key :
            The key of the integration configuraiton in the start document.
        """
        super().__init__()
        self.img_name = img_name
        integ_setting['unit'] = pyfai_unit
        self.integ_setting = integ_setting
        self.calibration_md_key = calibration_md_key
        self.x_name = units.MAP_PYFAI_TO_XNAME[pyfai_unit]
        self.y_name = units.MAP_PYFAI_TO_YNAME[pyfai_unit]
        self.x_unit = units.MAP_PYFAI_TO_MPL[pyfai_unit]
        self.y_unit = units.ARB
        if not self.x_name:
            raise ValueError("Unknown pyfai unit: '{}'.".format(pyfai_unit))
        self.integ_config_key = integ_config_key

    def start(self, doc):
        metadata = fs.strip_basics(doc)
        metadata[self.integ_config_key] = self.integ_setting
        metadata["hints"] = {"dimensions": [([self.x_name], "primary")]}
        self.calibration_md = doc.get(self.calibration_md_key)
        if not self.calibration_md:
            raise ValueNotFoundError(
                "Missing key '{}' in start (uid: {}).".format(self.calibration_md_key, doc["uid"])
            )
        self.crb = event_model.compose_run(metadata=metadata)
        return self.crb.start_doc

    def descriptor(self, doc):
        if not self.img_name:
            self.img_name = fd.find_one_array(doc["data_keys"])
        self.cbd: event_model.ComposeDescriptorBundle = self.crb.compose_descriptor(
            name="primary",
            data_keys={
                self.x_name: {
                    "dtype": "array",
                    "shape": [1],  # this is a fake shape for the waterfall plot to recognize it
                    "source": AzimuthalIntegration.__name__,
                    "units": self.x_unit
                },
                self.y_name: {
                    "dtype": "array",
                    "shape": [1],
                    "source": AzimuthalIntegration.__name__,
                    "units": self.y_unit
                },
            }
        )
        return self.cbd.descriptor_doc

    def event(self, doc):
        ai = io.load_ai_from_calib_result(self.calibration_md)
        img = fe.get_masked_array_from_event(doc, self.img_name)
        img_data = np.ma.getdata(img)
        # convert int because of the pyfai convention
        img_mask = np.ma.getmaskarray(img).astype(int)
        chi, _ = integrate(img_data, ai, mask=img_mask, integ_setting=self.integ_setting)
        t = time.time()
        return self.cbd.compose_event(
            data={
                self.x_name: chi[0],
                self.y_name: chi[1]
            },
            timestamps={
                self.x_name: t,
                self.y_name: t
            },
            filled={
                self.x_name: "yes",
                self.y_name: "yes"
            }
        )

    def stop(self, doc):
        return self.crb.compose_stop()


class TransformIQtoFQ(CallbackBase):
    """Transform from I(Q) to F(Q).

    The data from integration will be transformed to F(Q) in this step. The configuration of the transformation
    will be recorded in the start document.
    """

    def __init__(self, x_name: str = None, y_name: str = None, *, composition_key: str, wavelength_key: str,
                 pyfai_unit: str, trans_setting: dict, pdf_config_key: str = "pdf_config"):
        """Initiate the instance.

        Parameters
        ----------
        x_name :
            The name of the independent variable in the data keys like "Q".

        y_name :
            The name of the dependent variable in the data keys like "I".

        composition_key :
            The key of the sample composition info in the start document.

        wavelength_key :
            The key of the wavelength at the beam time in the start document.

        pyfai_unit :
            The input data format. See pyFAI for details.

        trans_setting :
            The setting of the transformation. See `diffpy.pdfgetx.PDFConfig` for detail.

        pdf_config_key :
            The key of the configuration that will be injected in the start document.
        """
        super().__init__()
        self.x_name = x_name
        self.y_name = y_name
        self.composition_key = composition_key
        self.wavelength_key = wavelength_key
        self.pyfai_unit = pyfai_unit
        self.dataformat = units.MAP_PYFAI_TO_DATAFORMAT[pyfai_unit]
        self.trans_setting = trans_setting
        self.pdf_config_key = pdf_config_key

    def start(self, doc):
        metadata = fs.strip_basics(doc)
        config = dict()
        bt_info = fs.query_bt_info(doc, composition_key=self.composition_key,
                                   wavelength_key=self.wavelength_key)
        bt_info["composition"] = bt_info.get("composition", "Ni")
        config.update(bt_info)
        config.update({"dataformat": self.dataformat})
        config.update(self.trans_setting)
        self.getter = PDFGetter(PDFConfig(**config))
        self.getter.transformations = self.getter.transformations[:-2]
        metadata[self.pdf_config_key] = config
        metadata["hints"] = {"dimensions": [(["Q"], "primary")]}
        self.crb = event_model.compose_run(metadata=metadata)
        return self.crb.start_doc

    def descriptor(self, doc):
        if not self.x_name:
            self.x_name = units.MAP_PYFAI_TO_XNAME[self.pyfai_unit]
        if not self.y_name:
            self.y_name = units.MAP_PYFAI_TO_YNAME[self.pyfai_unit]
        self.cbd = self.crb.compose_descriptor(
            name="primary",
            data_keys={
                "Q": {
                    "dtype": "array",
                    "shape": [1],
                    "source": TransformIQtoFQ.__name__,
                    "units": units.INV_A
                },
                "F": {
                    "dtype": "array",
                    "shape": [1],
                    "source": TransformIQtoFQ.__name__,
                    "units": units.INV_A
                }
            }
        )
        return self.cbd.descriptor_doc

    def event(self, doc):
        x = fe.get_array_from_event(doc, self.x_name)
        y = fe.get_array_from_event(doc, self.y_name)
        if self.pyfai_unit == "2th_rad":
            x = np.rad2deg(x)
        q, f = self.getter(x, y)
        t = time.time()
        return self.cbd.compose_event(
            data={
                "Q": q,
                "F": f
            },
            timestamps={
                "Q": t,
                "F": t
            },
            filled={
                "Q": "yes",
                "F": "yes"
            }
        )

    def stop(self, doc):
        return self.crb.compose_stop()


class TransformFQtoGr(CallbackBase):
    """Transformation from the F(Q) to G(r).

    The F(Q) will be fast fourier transformed to G(r) in this step. The configuration will be record in the start
    document.
    """

    def __init__(self, x_name: str = "Q", y_name: str = "F", *, grid_config: dict,
                 pdf_config_key: str = "pdf_config"):
        """Initiate the instance.

        Parameters
        ----------
        x_name :
            The name of the independent variable in the data keys like "Q".

        y_name :
            The name of the dependent variable in the data keys like "I".

        grid_config :
            The configuration of r-grid of the output. The allowed keys are rmin, rmax, and rstep.

        pdf_config_key :
            The key of the configuration that will be injected in the start document.
        """
        super().__init__()
        self.x_name = x_name
        self.y_name = y_name
        self.grid_config = grid_config
        self.pdf_config_key = pdf_config_key

    def start(self, doc):
        metadata = fs.strip_basics(doc)
        config = {}
        config.update(metadata.get(self.pdf_config_key, {}))
        config.update(self.grid_config)
        self.getter = PDFGetter(PDFConfig(**config))
        self.getter.transformations = self.getter.transformations[-2:]
        metadata[self.pdf_config_key] = config
        metadata["hints"] = {"dimensions": [(["r"], "primary")]}
        self.crb = event_model.compose_run(metadata=metadata)
        return self.crb.start_doc

    def descriptor(self, doc):
        self.cbd = self.crb.compose_descriptor(
            name="primary",
            data_keys={
                "r": {
                    "dtype": "array",
                    "shape": [1],
                    "source": TransformFQtoGr.__name__,
                    "units": units.A
                },
                "G": {
                    "dtype": "array",
                    "shape": [1],
                    "source": TransformFQtoGr.__name__,
                    "units": units.INV_SQ_A
                }
            }
        )
        return self.cbd.descriptor_doc

    def event(self, doc):
        x = fe.get_array_from_event(doc, self.x_name)
        y = fe.get_array_from_event(doc, self.y_name)
        r, g = self.getter(x, y)
        t = time.time()
        return self.cbd.compose_event(
            data={
                "r": r,
                "G": g
            },
            timestamps={
                "r": t,
                "G": t
            },
            filled={
                "r": "yes",
                "G": "yes"
            }
        )

    def stop(self, doc):
        return self.crb.compose_stop()
