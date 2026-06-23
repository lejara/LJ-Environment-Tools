import QtQuick 2.7
import QtQuick.Layouts 1.3
import Qt.labs.platform 1.1
import Qt.labs.folderlistmodel 2.12
import AlgWidgets 2.0
import AlgWidgets.Style 2.0

Item {
    id: root
    objectName: "ljSubPainterToolsPanel"
    width: 380
    height: 300

    property string title: "LJ Painter Tools"

    readonly property string keyPath: "ljSubPainterTools/exportPath"
    readonly property string keyPreset: "ljSubPainterTools/exportPreset"
    readonly property string keyPresetsFolder: "ljSubPainterTools/presetsFolder"

    readonly property string defaultPresetsFolder:
        "C:/Users/leone/OneDrive/Desktop/Blender Store/Substance Painter/Export Presets"

    readonly property string presetsFolderUrl:
        presetsFolderField.text
        ? "file:///" + presetsFolderField.text.replace(/\\/g, "/")
        : ""

    Component.onCompleted: {
        pathField.text = alg.settings.value(keyPath, "")
        presetsFolderField.text = alg.settings.value(keyPresetsFolder, defaultPresetsFolder)
    }

    function refreshPresetCombo() {
        var names = []
        for (var i = 0; i < presetsModel.count; i++) {
            var f = presetsModel.get(i, "fileName")
            names.push(f.replace(/\.spexp$/i, ""))
        }
        names.sort()
        presetCombo.model = names

        var saved = alg.settings.value(keyPreset, "")
        var idx = names.indexOf(saved)
        presetCombo.currentIndex = idx >= 0 ? idx : (names.length ? 0 : -1)

        alg.log.info("LJSubPainterTools: loaded " + names.length + " presets from " + presetsFolderUrl)
    }

    function doExport() {
        if (!pathField.text) {
            alg.log.warn("LJSubPainterTools: set an export path first")
            return
        }
        if (presetCombo.currentIndex < 0) {
            alg.log.warn("LJSubPainterTools: no export preset selected")
            return
        }

        alg.settings.setValue(keyPath, pathField.text)
        alg.settings.setValue(keyPreset, presetCombo.currentText)

        alg.log.info("LJSubPainterTools: export → " + pathField.text
                     + "  preset: " + presetCombo.currentText)
        // TODO: alg.mapexport.exportDocumentMaps(...)
    }

    function urlToLocalPath(url) {
        return url.replace(/^file:\/{2,3}/, "").replace(/^([A-Za-z]):/, "$1:")
    }

    FolderListModel {
        id: presetsModel
        folder: root.presetsFolderUrl
        nameFilters: ["*.spexp"]
        showDirs: false
        onStatusChanged: if (status === FolderListModel.Ready) root.refreshPresetCombo()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        AlgLabel { text: "LJ Exportor. For all your export needs!" }

        AlgLabel { text: "Presets Folder" }
        RowLayout {
            Layout.fillWidth: true
            spacing: 4

            AlgTextEdit {
                id: presetsFolderField
                Layout.fillWidth: true
                onTextChanged: alg.settings.setValue(root.keyPresetsFolder, text)
            }

            AlgButton {
                text: "…"
                implicitWidth: 32
                onClicked: presetsFolderDialog.open()
            }
        }

        AlgLabel { text: "Export Template" }
        AlgComboBox {
            id: presetCombo
            Layout.fillWidth: true
            onActivated: alg.settings.setValue(root.keyPreset, currentText)
        }

        AlgLabel { text: "Output Path" }
        RowLayout {
            Layout.fillWidth: true
            spacing: 4

            AlgTextEdit {
                id: pathField
                Layout.fillWidth: true
                onTextChanged: alg.settings.setValue(root.keyPath, text)
            }

            AlgButton {
                text: "…"
                implicitWidth: 32
                onClicked: folderDialog.open()
            }
        }

        AlgButton {
            text: "Export"
            Layout.fillWidth: true
            onClicked: doExport()
        }

        Item { Layout.fillHeight: true }
    }

    FolderDialog {
        id: folderDialog
        title: "Choose export folder"
        folder: pathField.text ? "file:///" + pathField.text.replace(/\\/g, "/") : ""
        onAccepted: pathField.text = root.urlToLocalPath(folder.toString())
    }

    FolderDialog {
        id: presetsFolderDialog
        title: "Choose presets folder"
        folder: presetsFolderField.text ? "file:///" + presetsFolderField.text.replace(/\\/g, "/") : ""
        onAccepted: presetsFolderField.text = root.urlToLocalPath(folder.toString())
    }
}
