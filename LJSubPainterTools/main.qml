import QtQuick 2.7
import Painter 1.0

PainterPlugin {
    Component.onCompleted: {
        alg.log.info("LJSubPainterTools: loaded")
        alg.ui.addDockWidget(Qt.resolvedUrl("panel.qml"))
    }
}
