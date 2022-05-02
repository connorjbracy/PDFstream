import typing as T
from bluesky.callbacks.zmq import RemoteDispatcher
from pdfstream.callbacks.config import Config
from pdfstream.callbacks.visualizationpipeline import VisualizationPipeline
from pdfstream.vend.qt_kicker import install_qt_kicker

PipeLine = T.ClassVar[Config]


class VisualizationServer(RemoteDispatcher):

    def __init__(self, config: Config) -> None:
        super().__init__(config.outbound_address, prefix=config.analyzed_data_prefix)
        pipeline = VisualizationPipeline(config)
        self.subscribe(pipeline)
        install_qt_kicker(self.loop)
