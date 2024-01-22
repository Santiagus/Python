# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'form.ui'
##
## Created by: Qt User Interface Compiler version 6.6.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QComboBox, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSizePolicy, QSpacerItem, QTableView, QWidget)

class Ui_WebScrapper(object):
    def setupUi(self, WebScrapper):
        if not WebScrapper.objectName():
            WebScrapper.setObjectName(u"WebScrapper")
        WebScrapper.resize(1061, 726)
        self.gridLayout = QGridLayout(WebScrapper)
        self.gridLayout.setObjectName(u"gridLayout")
        self.groupSrc = QGroupBox(WebScrapper)
        self.groupSrc.setObjectName(u"groupSrc")
        self.gridLayout_3 = QGridLayout(self.groupSrc)
        self.gridLayout_3.setObjectName(u"gridLayout_3")
        self.btSearch = QPushButton(self.groupSrc)
        self.btSearch.setObjectName(u"btSearch")

        self.gridLayout_3.addWidget(self.btSearch, 0, 3, 1, 1)

        self.lbRegExp_2 = QLabel(self.groupSrc)
        self.lbRegExp_2.setObjectName(u"lbRegExp_2")

        self.gridLayout_3.addWidget(self.lbRegExp_2, 1, 0, 1, 1)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.gridLayout_3.addItem(self.horizontalSpacer, 0, 2, 1, 1)

        self.lbRegExp = QLabel(self.groupSrc)
        self.lbRegExp.setObjectName(u"lbRegExp")

        self.gridLayout_3.addWidget(self.lbRegExp, 0, 0, 1, 1)

        self.lnRegExp = QLineEdit(self.groupSrc)
        self.lnRegExp.setObjectName(u"lnRegExp")

        self.gridLayout_3.addWidget(self.lnRegExp, 0, 1, 1, 1)

        self.btSourceClr = QPushButton(self.groupSrc)
        self.btSourceClr.setObjectName(u"btSourceClr")

        self.gridLayout_3.addWidget(self.btSourceClr, 0, 6, 1, 1)

        self.btRegExp = QPushButton(self.groupSrc)
        self.btRegExp.setObjectName(u"btRegExp")

        self.gridLayout_3.addWidget(self.btRegExp, 0, 4, 1, 1)

        self.btSaveRegExp = QPushButton(self.groupSrc)
        self.btSaveRegExp.setObjectName(u"btSaveRegExp")

        self.gridLayout_3.addWidget(self.btSaveRegExp, 0, 5, 1, 1)

        self.cbLoadedRegExp = QComboBox(self.groupSrc)
        self.cbLoadedRegExp.setObjectName(u"cbLoadedRegExp")

        self.gridLayout_3.addWidget(self.cbLoadedRegExp, 1, 1, 1, 6)


        self.gridLayout.addWidget(self.groupSrc, 6, 1, 1, 4)

        self.groupOutput = QGroupBox(WebScrapper)
        self.groupOutput.setObjectName(u"groupOutput")
        self.gridLayout_4 = QGridLayout(self.groupOutput)
        self.gridLayout_4.setObjectName(u"gridLayout_4")
        self.lbRegExp_3 = QLabel(self.groupOutput)
        self.lbRegExp_3.setObjectName(u"lbRegExp_3")

        self.gridLayout_4.addWidget(self.lbRegExp_3, 2, 0, 1, 1)

        self.btCopy2Src = QPushButton(self.groupOutput)
        self.btCopy2Src.setObjectName(u"btCopy2Src")

        self.gridLayout_4.addWidget(self.btCopy2Src, 0, 5, 1, 1)

        self.btLoadLinks = QPushButton(self.groupOutput)
        self.btLoadLinks.setObjectName(u"btLoadLinks")

        self.gridLayout_4.addWidget(self.btLoadLinks, 0, 6, 1, 1)

        self.btOutputClr = QPushButton(self.groupOutput)
        self.btOutputClr.setObjectName(u"btOutputClr")

        self.gridLayout_4.addWidget(self.btOutputClr, 0, 8, 1, 1)

        self.lnSQLQuery = QLineEdit(self.groupOutput)
        self.lnSQLQuery.setObjectName(u"lnSQLQuery")

        self.gridLayout_4.addWidget(self.lnSQLQuery, 2, 1, 1, 8)

        self.btSaveOutput = QPushButton(self.groupOutput)
        self.btSaveOutput.setObjectName(u"btSaveOutput")

        self.gridLayout_4.addWidget(self.btSaveOutput, 0, 7, 1, 1)

        self.btMiDiaStats = QPushButton(self.groupOutput)
        self.btMiDiaStats.setObjectName(u"btMiDiaStats")

        self.gridLayout_4.addWidget(self.btMiDiaStats, 0, 2, 1, 1)

        self.btGetRascas = QPushButton(self.groupOutput)
        self.btGetRascas.setObjectName(u"btGetRascas")

        self.gridLayout_4.addWidget(self.btGetRascas, 0, 3, 1, 1)

        self.btGetData = QPushButton(self.groupOutput)
        self.btGetData.setObjectName(u"btGetData")

        self.gridLayout_4.addWidget(self.btGetData, 0, 0, 1, 1)

        self.btRascaStats = QPushButton(self.groupOutput)
        self.btRascaStats.setObjectName(u"btRascaStats")

        self.gridLayout_4.addWidget(self.btRascaStats, 0, 4, 1, 1)


        self.gridLayout.addWidget(self.groupOutput, 6, 6, 1, 3)

        self.frame = QFrame(WebScrapper)
        self.frame.setObjectName(u"frame")
        self.frame.setFrameShape(QFrame.StyledPanel)
        self.frame.setFrameShadow(QFrame.Raised)

        self.gridLayout.addWidget(self.frame, 7, 0, 1, 1)

        self.txtOutput = QPlainTextEdit(WebScrapper)
        self.txtOutput.setObjectName(u"txtOutput")

        self.gridLayout.addWidget(self.txtOutput, 7, 6, 1, 1)

        self.txtSrc = QPlainTextEdit(WebScrapper)
        self.txtSrc.setObjectName(u"txtSrc")
        self.txtSrc.setStyleSheet(u"selection-background-color: rgb(85, 255, 0);")
        self.txtSrc.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)

        self.gridLayout.addWidget(self.txtSrc, 7, 1, 5, 4)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setSpacing(6)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.lbUrl = QLabel(WebScrapper)
        self.lbUrl.setObjectName(u"lbUrl")

        self.horizontalLayout.addWidget(self.lbUrl)

        self.lnUrl = QLineEdit(WebScrapper)
        self.lnUrl.setObjectName(u"lnUrl")

        self.horizontalLayout.addWidget(self.lnUrl)

        self.cbLinks = QComboBox(WebScrapper)
        self.cbLinks.setObjectName(u"cbLinks")
        sizePolicy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.cbLinks.sizePolicy().hasHeightForWidth())
        self.cbLinks.setSizePolicy(sizePolicy)

        self.horizontalLayout.addWidget(self.cbLinks)

        self.btUrl = QPushButton(WebScrapper)
        self.btUrl.setObjectName(u"btUrl")

        self.horizontalLayout.addWidget(self.btUrl)


        self.gridLayout.addLayout(self.horizontalLayout, 0, 1, 1, 8)

        self.lbOutputInfo = QLabel(WebScrapper)
        self.lbOutputInfo.setObjectName(u"lbOutputInfo")

        self.gridLayout.addWidget(self.lbOutputInfo, 12, 6, 1, 3)

        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.Filters = QGroupBox(WebScrapper)
        self.Filters.setObjectName(u"Filters")
        self.gridLayout_2 = QGridLayout(self.Filters)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.btClearAttr = QPushButton(self.Filters)
        self.btClearAttr.setObjectName(u"btClearAttr")
        sizePolicy1 = QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.btClearAttr.sizePolicy().hasHeightForWidth())
        self.btClearAttr.setSizePolicy(sizePolicy1)
        self.btClearAttr.setMinimumSize(QSize(20, 20))
        self.btClearAttr.setMaximumSize(QSize(20, 20))
        font = QFont()
        font.setFamilies([u"Wingdings 2"])
        font.setPointSize(16)
        self.btClearAttr.setFont(font)
        self.btClearAttr.setText(u"O")

        self.gridLayout_2.addWidget(self.btClearAttr, 0, 4, 1, 1)

        self.lbAttrValue = QLabel(self.Filters)
        self.lbAttrValue.setObjectName(u"lbAttrValue")

        self.gridLayout_2.addWidget(self.lbAttrValue, 0, 5, 1, 1)

        self.cbAttributes = QComboBox(self.Filters)
        self.cbAttributes.setObjectName(u"cbAttributes")
        self.cbAttributes.setMinimumSize(QSize(100, 0))

        self.gridLayout_2.addWidget(self.cbAttributes, 0, 3, 1, 1)

        self.btClearAttrValue = QPushButton(self.Filters)
        self.btClearAttrValue.setObjectName(u"btClearAttrValue")
        sizePolicy1.setHeightForWidth(self.btClearAttrValue.sizePolicy().hasHeightForWidth())
        self.btClearAttrValue.setSizePolicy(sizePolicy1)
        self.btClearAttrValue.setMinimumSize(QSize(20, 20))
        self.btClearAttrValue.setMaximumSize(QSize(20, 20))
        self.btClearAttrValue.setFont(font)
        self.btClearAttrValue.setText(u"O")

        self.gridLayout_2.addWidget(self.btClearAttrValue, 0, 7, 1, 1)

        self.cbAttrValue = QComboBox(self.Filters)
        self.cbAttrValue.setObjectName(u"cbAttrValue")
        self.cbAttrValue.setMinimumSize(QSize(100, 0))

        self.gridLayout_2.addWidget(self.cbAttrValue, 0, 6, 1, 1)

        self.lbTag = QLabel(self.Filters)
        self.lbTag.setObjectName(u"lbTag")

        self.gridLayout_2.addWidget(self.lbTag, 0, 0, 1, 1)

        self.cbLoadedFilters = QComboBox(self.Filters)
        self.cbLoadedFilters.setObjectName(u"cbLoadedFilters")

        self.gridLayout_2.addWidget(self.cbLoadedFilters, 1, 3, 1, 4)

        self.lbAttributes = QLabel(self.Filters)
        self.lbAttributes.setObjectName(u"lbAttributes")

        self.gridLayout_2.addWidget(self.lbAttributes, 0, 2, 1, 1)

        self.cbTags = QComboBox(self.Filters)
        self.cbTags.setObjectName(u"cbTags")

        self.gridLayout_2.addWidget(self.cbTags, 0, 1, 1, 1)

        self.btApplyComboFilter = QPushButton(self.Filters)
        self.btApplyComboFilter.setObjectName(u"btApplyComboFilter")

        self.gridLayout_2.addWidget(self.btApplyComboFilter, 1, 8, 1, 1)

        self.btSaveFilters = QPushButton(self.Filters)
        self.btSaveFilters.setObjectName(u"btSaveFilters")

        self.gridLayout_2.addWidget(self.btSaveFilters, 1, 10, 1, 1)

        self.label = QLabel(self.Filters)
        self.label.setObjectName(u"label")

        self.gridLayout_2.addWidget(self.label, 1, 0, 1, 2)

        self.btFilter = QPushButton(self.Filters)
        self.btFilter.setObjectName(u"btFilter")

        self.gridLayout_2.addWidget(self.btFilter, 0, 8, 1, 1)

        self.btGetText = QPushButton(self.Filters)
        self.btGetText.setObjectName(u"btGetText")

        self.gridLayout_2.addWidget(self.btGetText, 0, 10, 1, 1)


        self.horizontalLayout_3.addWidget(self.Filters)

        self.Extract = QGroupBox(WebScrapper)
        self.Extract.setObjectName(u"Extract")
        self.Extract.setMinimumSize(QSize(0, 0))
        self.horizontalLayout_4 = QHBoxLayout(self.Extract)
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.lbAttr2Extract = QLabel(self.Extract)
        self.lbAttr2Extract.setObjectName(u"lbAttr2Extract")

        self.horizontalLayout_4.addWidget(self.lbAttr2Extract)

        self.cbAttr2Extract = QComboBox(self.Extract)
        self.cbAttr2Extract.setObjectName(u"cbAttr2Extract")
        self.cbAttr2Extract.setMinimumSize(QSize(100, 0))

        self.horizontalLayout_4.addWidget(self.cbAttr2Extract)

        self.btClearAttr2Extract = QPushButton(self.Extract)
        self.btClearAttr2Extract.setObjectName(u"btClearAttr2Extract")
        sizePolicy1.setHeightForWidth(self.btClearAttr2Extract.sizePolicy().hasHeightForWidth())
        self.btClearAttr2Extract.setSizePolicy(sizePolicy1)
        self.btClearAttr2Extract.setMinimumSize(QSize(20, 20))
        self.btClearAttr2Extract.setMaximumSize(QSize(20, 20))
        self.btClearAttr2Extract.setFont(font)
        self.btClearAttr2Extract.setText(u"O")

        self.horizontalLayout_4.addWidget(self.btClearAttr2Extract)

        self.btGetAttrValues = QPushButton(self.Extract)
        self.btGetAttrValues.setObjectName(u"btGetAttrValues")

        self.horizontalLayout_4.addWidget(self.btGetAttrValues)


        self.horizontalLayout_3.addWidget(self.Extract)


        self.gridLayout.addLayout(self.horizontalLayout_3, 4, 1, 1, 8)

        self.lbSrcCodeInfo = QLabel(WebScrapper)
        self.lbSrcCodeInfo.setObjectName(u"lbSrcCodeInfo")

        self.gridLayout.addWidget(self.lbSrcCodeInfo, 12, 1, 1, 3)

        self.tableView = QTableView(WebScrapper)
        self.tableView.setObjectName(u"tableView")
        sizePolicy2 = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.tableView.sizePolicy().hasHeightForWidth())
        self.tableView.setSizePolicy(sizePolicy2)

        self.gridLayout.addWidget(self.tableView, 11, 6, 1, 1)

        self.TableControls = QHBoxLayout()
        self.TableControls.setObjectName(u"TableControls")
        self.lbTables = QLabel(WebScrapper)
        self.lbTables.setObjectName(u"lbTables")

        self.TableControls.addWidget(self.lbTables)

        self.cbTables = QComboBox(WebScrapper)
        self.cbTables.setObjectName(u"cbTables")
        self.cbTables.setMinimumSize(QSize(100, 0))

        self.TableControls.addWidget(self.cbTables)

        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.TableControls.addItem(self.horizontalSpacer_2)

        self.btAddRow = QPushButton(WebScrapper)
        self.btAddRow.setObjectName(u"btAddRow")
        self.btAddRow.setMaximumSize(QSize(23, 23))
        font1 = QFont()
        font1.setPointSize(10)
        font1.setBold(True)
        self.btAddRow.setFont(font1)

        self.TableControls.addWidget(self.btAddRow)

        self.btRemoveRow = QPushButton(WebScrapper)
        self.btRemoveRow.setObjectName(u"btRemoveRow")
        self.btRemoveRow.setMaximumSize(QSize(23, 23))
        self.btRemoveRow.setFont(font1)

        self.TableControls.addWidget(self.btRemoveRow)

        self.btClearTable = QPushButton(WebScrapper)
        self.btClearTable.setObjectName(u"btClearTable")

        self.TableControls.addWidget(self.btClearTable)

        self.btRevert = QPushButton(WebScrapper)
        self.btRevert.setObjectName(u"btRevert")

        self.TableControls.addWidget(self.btRevert)

        self.btSubmit = QPushButton(WebScrapper)
        self.btSubmit.setObjectName(u"btSubmit")

        self.TableControls.addWidget(self.btSubmit)


        self.gridLayout.addLayout(self.TableControls, 8, 6, 1, 1)


        self.retranslateUi(WebScrapper)
        self.lnUrl.returnPressed.connect(self.btUrl.click)
        self.btSourceClr.clicked.connect(self.txtSrc.clear)
        self.btOutputClr.clicked.connect(self.txtOutput.clear)
        self.btClearAttr.clicked.connect(self.cbAttributes.clear)
        self.btClearAttrValue.clicked.connect(self.cbAttrValue.clear)
        self.lnRegExp.returnPressed.connect(self.btRegExp.click)
        self.btClearAttr2Extract.clicked.connect(self.cbAttr2Extract.clear)
        self.txtSrc.blockCountChanged.connect(self.lbSrcCodeInfo.setNum)
        self.txtOutput.blockCountChanged.connect(self.lbOutputInfo.setNum)

        QMetaObject.connectSlotsByName(WebScrapper)
    # setupUi

    def retranslateUi(self, WebScrapper):
        WebScrapper.setWindowTitle(QCoreApplication.translate("WebScrapper", u"WebScrapper", None))
        self.groupSrc.setTitle(QCoreApplication.translate("WebScrapper", u"Source Code", None))
        self.btSearch.setText(QCoreApplication.translate("WebScrapper", u"Search", None))
        self.lbRegExp_2.setText(QCoreApplication.translate("WebScrapper", u"RegExp", None))
        self.lbRegExp.setText(QCoreApplication.translate("WebScrapper", u"RegExp", None))
        self.lnRegExp.setText(QCoreApplication.translate("WebScrapper", u"\\d+[.,]?\\d*", None))
        self.btSourceClr.setText(QCoreApplication.translate("WebScrapper", u"Clear", None))
        self.btRegExp.setText(QCoreApplication.translate("WebScrapper", u"Apply", None))
        self.btSaveRegExp.setText(QCoreApplication.translate("WebScrapper", u"Save", None))
        self.groupOutput.setTitle(QCoreApplication.translate("WebScrapper", u"GroupBox", None))
        self.lbRegExp_3.setText(QCoreApplication.translate("WebScrapper", u"SQL Query", None))
        self.btCopy2Src.setText(QCoreApplication.translate("WebScrapper", u"Copy 2 Src", None))
        self.btLoadLinks.setText(QCoreApplication.translate("WebScrapper", u"LoadLinks", None))
        self.btOutputClr.setText(QCoreApplication.translate("WebScrapper", u"Clear", None))
        self.lnSQLQuery.setText(QCoreApplication.translate("WebScrapper", u"select * from game_info", None))
        self.btSaveOutput.setText(QCoreApplication.translate("WebScrapper", u"Save2File", None))
        self.btMiDiaStats.setText(QCoreApplication.translate("WebScrapper", u"MiDiaStats", None))
        self.btGetRascas.setText(QCoreApplication.translate("WebScrapper", u"GetRascas", None))
        self.btGetData.setText(QCoreApplication.translate("WebScrapper", u"GetMiDia", None))
        self.btRascaStats.setText(QCoreApplication.translate("WebScrapper", u"RascaStats", None))
        self.txtSrc.setPlainText(QCoreApplication.translate("WebScrapper", u"Premios por cada serie de boletos de ([0-9]+\\.?[0-9]+\\.?[0-9]+\\.?)\n"
"\\d+[.,]?\\d\n"
"", None))
        self.lbUrl.setText(QCoreApplication.translate("WebScrapper", u"URL: ", None))
        self.lnUrl.setText(QCoreApplication.translate("WebScrapper", u"https://www.juegosonce.es/rascas-todos", None))
        self.btUrl.setText(QCoreApplication.translate("WebScrapper", u"Load", None))
        self.lbOutputInfo.setText("")
        self.Filters.setTitle(QCoreApplication.translate("WebScrapper", u"Filters", None))
        self.lbAttrValue.setText(QCoreApplication.translate("WebScrapper", u"AttrValue", None))
        self.lbTag.setText(QCoreApplication.translate("WebScrapper", u"Tags", None))
        self.lbAttributes.setText(QCoreApplication.translate("WebScrapper", u"Attr", None))
        self.btApplyComboFilter.setText(QCoreApplication.translate("WebScrapper", u"Apply", None))
        self.btSaveFilters.setText(QCoreApplication.translate("WebScrapper", u"Save", None))
        self.label.setText(QCoreApplication.translate("WebScrapper", u"Load Filter", None))
        self.btFilter.setText(QCoreApplication.translate("WebScrapper", u"Filter Tags", None))
        self.btGetText.setText(QCoreApplication.translate("WebScrapper", u"Get Text", None))
        self.Extract.setTitle(QCoreApplication.translate("WebScrapper", u"Extract", None))
        self.lbAttr2Extract.setText(QCoreApplication.translate("WebScrapper", u"Attr", None))
        self.btGetAttrValues.setText(QCoreApplication.translate("WebScrapper", u"Get", None))
        self.lbSrcCodeInfo.setText("")
        self.lbTables.setText(QCoreApplication.translate("WebScrapper", u"Tables", None))
        self.btAddRow.setText(QCoreApplication.translate("WebScrapper", u"+", None))
        self.btRemoveRow.setText(QCoreApplication.translate("WebScrapper", u"-", None))
        self.btClearTable.setText(QCoreApplication.translate("WebScrapper", u"Clear Table", None))
        self.btRevert.setText(QCoreApplication.translate("WebScrapper", u"Revert", None))
        self.btSubmit.setText(QCoreApplication.translate("WebScrapper", u"Submit", None))
    # retranslateUi

