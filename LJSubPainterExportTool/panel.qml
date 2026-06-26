import QtQuick 2.7
import QtQuick.Layouts 1.3
import Qt.labs.platform 1.1
import Qt.labs.folderlistmodel 2.12
import AlgWidgets 2.0
import AlgWidgets.Style 2.0

Item {
    id: root
    objectName: "LJ Export Tool"
    width: 380
    height: 340

    property string title: "LJ Export Tool"

    readonly property string keyPath: "ljSubPainterExportTool/exportPath"
    readonly property string keyPreset: "ljSubPainterExportTool/exportPreset"
    readonly property string keyPresetsFolder: "ljSubPainterExportTool/presetsFolder"
    readonly property string keyFilename: "ljSubPainterExportTool/filename"

    readonly property string defaultPresetsFolder:
        "C:/Users/leone/OneDrive/Desktop/Blender Store/Substance Painter/Export Presets"

    readonly property string presetsFolderUrl:
        presetsFolderField.text
        ? "file:///" + presetsFolderField.text.replace(/\\/g, "/")
        : ""

    Component.onCompleted: {
        pathField.text = alg.settings.value(keyPath, "")
        presetsFolderField.text = alg.settings.value(keyPresetsFolder, defaultPresetsFolder)
        loadProjectFilename()
    }

    function loadProjectFilename() {
        if (alg.project.isOpen()) {
            filenameField.text = alg.project.settings.value(keyFilename, "")
        } else {
            filenameField.text = ""
        }
    }

    function clearProjectFilename() {
        filenameField.text = ""
    }

    function saveProjectFilename() {
        if (alg.project.isOpen()) {
            alg.project.settings.setValue(keyFilename, filenameField.text)
        }
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

        alg.log.info("LJSubPainterExportTool: loaded " + names.length + " presets from " + presetsFolderUrl)
    }

    function doExport() {
        if (!pathField.text) {
            alg.log.warn("LJSubPainterExportTool: set a root folder first")
            return
        }
        if (!filenameField.text) {
            alg.log.warn("LJSubPainterExportTool: set a filename first")
            return
        }
        if (presetCombo.currentIndex < 0) {
            alg.log.warn("LJSubPainterExportTool: no export preset selected")
            return
        }
        if (!alg.project.isOpen()) {
            alg.log.warn("LJSubPainterExportTool: no project open")
            return
        }

        alg.settings.setValue(keyPath, pathField.text)
        alg.settings.setValue(keyPreset, presetCombo.currentText)
        saveProjectFilename()

        var filename = filenameField.text
        var rootFolder = pathField.text.replace(/\\/g, "/").replace(/\/+$/, "")
        var exportFolder = rootFolder + "/" + filename
        var presetsFolder = presetsFolderField.text.replace(/\\/g, "/").replace(/\/+$/, "")
        var presetPath = presetsFolder + "/" + presetCombo.currentText + ".spexp"

        if (!alg.fileIO.exists(presetPath)) {
            alg.log.error("LJSubPainterExportTool: preset file not found → " + presetPath)
            return
        }

        alg.subprocess.call(["cmd.exe", "/c", "mkdir", exportFolder.replace(/\//g, "\\")])

        alg.log.info("LJSubPainterExportTool: exporting → " + exportFolder
                     + "  preset: " + presetPath)

        try {
            var result = alg.mapexport.exportDocumentMaps(
                presetPath,
                exportFolder,
                "png",
                {padding: "Infinite"},
                []
            )

            var renamed = 0
            for (var stack in result) {
                var maps = result[stack]
                for (var mapKey in maps) {
                    var oldPath = maps[mapKey]
                    if (!oldPath) continue
                    oldPath = oldPath.replace(/\\/g, "/")
                    var slashIdx = oldPath.lastIndexOf("/")
                    var dir = oldPath.substring(0, slashIdx)
                    var oldName = oldPath.substring(slashIdx + 1)
                    var dotIdx = oldName.lastIndexOf(".")
                    var ext = dotIdx >= 0 ? oldName.substring(dotIdx) : ""

                    var keyParts = mapKey.split("_")
                    var lastTokenIdx = -1
                    for (var j = 0; j < keyParts.length; j++) {
                        if (keyParts[j].charAt(0) === "$") lastTokenIdx = j
                    }
                    var mapName = keyParts.slice(lastTokenIdx + 1).join("_")
                    if (!mapName) mapName = mapKey

                    var newName = filename + "_" + mapName + ext
                    if (oldName === newName) continue
                    var srcWin = (dir + "/" + oldName).replace(/\//g, "\\")
                    var dstWin = (dir + "/" + newName).replace(/\//g, "\\")
                    alg.subprocess.call(["cmd.exe", "/c", "move", "/y", srcWin, dstWin])
                    renamed++
                }
            }

            alg.log.info("LJSubPainterExportTool: exported " + renamed + " maps to " + exportFolder)
        } catch (e) {
            alg.log.error("LJSubPainterExportTool: export failed → " + e)
            alg.log.exception(e)
        }
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

        AlgLabel { text: "Root Folder" }
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

        AlgLabel { text: "Filename (appended to each texture)" }
        AlgTextEdit {
            id: filenameField
            Layout.fillWidth: true
            onTextChanged: root.saveProjectFilename()
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
