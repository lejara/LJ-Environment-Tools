import QtQuick 2.7
import Painter 1.0

PainterPlugin {
    property var panel: null

    Component.onCompleted: {
        alg.log.info("LJSubPainterExportTool: loaded")
        panel = alg.ui.addDockWidget(Qt.resolvedUrl("panel.qml"))
    }

    onProjectOpened: if (panel) panel.loadProjectFilename()
    onNewProjectCreated: if (panel) panel.loadProjectFilename()
    onProjectAboutToClose: if (panel) panel.clearProjectFilename()
}
