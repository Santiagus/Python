# This Python file uses the following encoding: utf-8
import os
import sys
import re
from tokenize import Octnumber
from unittest import result
import requests
from db_handler import db_handler
import mi_dia
import rascas

from bs4 import BeautifulSoup
from PySide6.QtCore import SIGNAL, SLOT, QObject, Slot
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox, QComboBox
from PySide6.QtSql import QSqlTableModel, QSqlQueryModel
from PySide6.QtGui import QTextCursor
from ui_form import Ui_WebScrapper

class WebScrapper(QWidget):    
    
    def __init__(self):
        super(WebScrapper, self).__init__()
        self.ui = Ui_WebScrapper()
        self.ui.setupUi(self)
        self.db = db_handler()
        self.db.init_db()        

        # Buttons connections
        self.ui.btUrl.clicked.connect(self.loadWebSrc)
        self.ui.btFilter.clicked.connect(self.updateOutput)        
        self.ui.btGetText.clicked.connect(self.getTagsText)
        self.ui.btGetAttrValues.clicked.connect(self.getAttrValues)
        self.ui.btLoadLinks.clicked.connect(self.loadLinks)
        self.ui.btCopy2Src.clicked.connect(self.copy2Src)
        self.ui.btRegExp.clicked.connect(self.applyRegExp)
        self.ui.btSearch.clicked.connect(self.searchRegExp)
        self.ui.btSaveFilters.clicked.connect(self.saveFilters2File)        
        self.ui.btSaveRegExp.clicked.connect(self.saveRegExp2File)        
        self.ui.btApplyComboFilter.clicked.connect(self.applyFilter)
        self.ui.btSubmit.clicked.connect(self.submitTable)
        self.ui.btAddRow.clicked.connect(self.addRow)
        self.ui.btRemoveRow.clicked.connect(lambda: self.model.removeRow(self.model.rowCount()-1))
        self.ui.btGetData.clicked.connect(self.updateMiDiaResults)
        self.ui.btClearTable.clicked.connect(self.clearTable)
        self.ui.btMiDiaStats.clicked.connect(self.printMiDiaStats)
        self.ui.btGetRascas.clicked.connect(self.getRascasInfo)
        
        # Combo Box connections
        self.ui.cbTags.currentIndexChanged.connect(self.listAttributes)        
        self.ui.cbAttributes.currentIndexChanged.connect(self.listAttributesValues)        
        self.ui.cbLinks.currentIndexChanged.connect(self.loadLink)
        self.ui.cbLoadedRegExp.currentIndexChanged.connect(self.loadRegExp)
        # Enter Press connecionts
        self.ui.lnSQLQuery.returnPressed.connect(self.execQuery)
        self.ui.cbTables.currentTextChanged.connect(self.loadTable)
        
        self.loadFilters()
        self.loadRegExpFromFile()

        # Table View
        #self.model = QSqlTableModel()
        self.model = QSqlQueryModel()
        # self.model.setEditStrategy(QSqlTableModel.OnManualSubmit)
        # self.model.select()

        self.ui.btRevert.clicked.connect(self.model.revert)
        self.loadTablesNames() # Load cb with tables names
        
    def loadTablesNames(self):
        print("loadTablesNames")
        print("tables : ", self.db.tables())
        tablesQuery = "SELECT name FROM sqlite_schema WHERE type ='table' AND name NOT LIKE 'sqlite_%'"        
        query = self.db.exec_query(tablesQuery)        
        # print(self.db.querytoString(query))
        self.ui.cbTables.clear()
        while query.next():
            name = query.value(0)
            self.ui.cbTables.addItem(name)
        if self.ui.cbTables.count():
            self.loadTable()
        
    @Slot()
    def addRow(self):
        #lambda: 
        self.model.insertRow(self.model.rowCount())
        #pragma_foreign_key_list(id,seq,"table","from","to",on_update,on_delete,"match")        
        return
        # Check foreing key
        sqlquery = "SELECT * FROM pragma_foreign_key_list('" + self.ui.cbTables.currentText() + "')"
        query = db_handler.exec_query(sqlquery)
        if query.next():
            fromTable = query.value('table')  # Save table were foreign key match
            idFrom  = query.value('from')
            idTo  = query.value('to')
            # Get 2nd field name from the table
            sqlquery = "SELECT name FROM pragma_table_info('"+ fromTable + "') LIMIT 1 OFFSET 1"
            query = db_handler.exec_query(sqlquery)
            if query.next():
                secondFieldName = query.value('name')
            # Get values
            sqlquery = "SELECT " + secondFieldName + " FROM "+ fromTable
            query = db_handler.exec_query(sqlquery)
            values = list()
            while query.next():
                val = query.value(secondFieldName)
                values.append(val)
            combo = QComboBox()
            combo.addItems(values)
            numRows = self.model.rowCount()            
            self.model.insertRow(numRows)
            i = self.model.index(numRows, 0)
            self.ui.tableView.setIndexWidget(i, combo)            

    @Slot()
    def loadTable(self):
        #self.model.setTable(self.ui.cbTables.currentText())        
        self.model.setQuery("SELECT * FROM " + self.ui.cbTables.currentText())
        #self.model.select()
        self.ui.tableView.setModel(self.model)        

    @Slot()
    def execQuery(self):        
        self.model.setQuery(self.ui.lnSQLQuery.text())
        self.ui.tableView.setModel(self.model)
        return

        sql_query = self.ui.lnSQLQuery.text()
        query = self.db.exec_query(sql_query)
        if query.isValid():
            #print(self.db.querytoString(query))
            #query.first()
            self.model.setQuery(query)
            # self.model.select()
            self.ui.tableView.setModel(self.model)            
        else:
            print("SQL Query is not valid")


    @Slot()
    def applyFilter(self):
        values = self.ui.cbLoadedFilters.currentText().split(";")
        
        index = self.ui.cbTags.findText(values[0])
        if index >= 0:
            self.ui.cbTags.setCurrentIndex(index)

        index = self.ui.cbAttributes.findText(values[1])
        if index >= 0:
            self.ui.cbAttributes.setCurrentIndex(index)
        
        index = self.ui.cbAttrValue.findText(values[2])        
        if index >= 0:
            self.ui.cbAttrValue.setCurrentIndex(index)

        index = self.ui.cbAttr2Extract.findText(values[3])
        if index >= 0:
            self.ui.cbAttr2Extract.setCurrentIndex(index)
            self.ui.btGetAttrValues.click()
        else:
            self.ui.btFilter.click()

    @Slot()
    def saveFilters2File(self):
        f = open("SavedFilters.csv", "a")
        data = (self.ui.cbTags.currentText(),
                self.ui.cbAttributes.currentText(),
                self.ui.cbAttrValue.currentText(),
                self.ui.cbAttr2Extract.currentText())
        f.write("%s;%s;%s;%s;\n" % data)
        f.close()
        print("Saved %s;%s;%s;%s;\n to SavedFilters.csv" % data)
        self.loadFilters()

    @Slot()
    def loadFilters(self):
        print(sys._getframe().f_code.co_name)
        if not os.path.exists("SavedFilters.csv"):
          print("The file does not exist")
          return
        #open and read the file after the appending:
        f = open("SavedFilters.csv", "r")
        self.ui.cbLoadedFilters.clear()
        self.ui.cbLoadedFilters.addItems(item.rstrip("\n") for item in f.readlines())
    
    @Slot()
    def loadRegExpFromFile(self):
        print(sys._getframe().f_code.co_name)
        if not os.path.exists("RegExps.csv"):
          print("The file does not exist")
          return
        #open and read the file after the appending:
        f = open("RegExps.csv", "r")
        self.ui.cbLoadedRegExp.clear()
        self.ui.cbLoadedRegExp.addItems(item.rstrip("\n") for item in f.readlines())

    @Slot()
    def saveRegExp2File(self):
        f = open("RegExps.csv", "a")        
        f.write(self.ui.lnRegExp.text() + "\n")
        f.close()
        print("Saved %s to RegExps.csv" % self.ui.lnRegExp.text())
        self.loadRegExpFromFile()

    @Slot()
    def copy2Src(self):
        self.ui.txtSrc.setPlainText(self.ui.txtOutput.toPlainText())

    @Slot()
    def searchRegExp(self):
        self.ui.txtSrc.find(self.ui.lnRegExp.text())

    @Slot()
    def applyRegExp(self):
        pattern = self.ui.lnRegExp.text()
        string = self.ui.txtSrc.toPlainText()
        result = re.findall(pattern,string)
        print(result)
        self.ui.txtOutput.setPlainText("".join(x + "\n" for x in result))
        self.ui.txtSrc.find(pattern)
        
    @Slot()
    def listTags(self):   
        self.docTags = set()
        self.ui.cbTags.clear()
        self.ui.cbAttributes.clear()
        self.ui.cbAttrValue.clear()
        for item in self.soup.findAll(True):
            self.docTags.add(item.name)        
        self.ui.cbTags.addItems(sorted(self.docTags))        
        self.ui.lbTag.setText("Tags ({0})".format(self.ui.cbTags.count()))
        

    @Slot()
    def listAttributes(self):
        if not self.ui.cbTags.currentText():
            return        
        self.ui.cbAttributes.clear()
        self.ui.cbAttrValue.clear()
        tags = self.soup.findAll(self.ui.cbTags.currentText())
        attributeSet = set()
        for item in tags:
            for attribute in item.attrs.keys():
                attributeSet.add(attribute)
        self.ui.cbAttributes.addItems(sorted(attributeSet))
        self.ui.lbAttributes.setText("Attr ({0})".format(self.ui.cbAttributes.count()))
        self.ui.cbAttr2Extract.addItems(sorted(attributeSet))
        self.ui.lbAttr2Extract.setText("Attr ({0})".format(self.ui.cbAttributes.count()))

    
    @Slot()
    def listAttributesValues(self):
        if not self.ui.cbTags.currentText():
            return
        if not self.ui.cbAttributes.currentText():
            return                
        self.ui.cbAttrValue.clear()
        tags = self.soup.findAll(self.ui.cbTags.currentText())
        values = set()
        for item in tags:
            value = item.get(self.ui.cbAttributes.currentText())
            if value:
                for item in value:                                
                    values.add(item)
        self.ui.cbAttrValue.addItems(sorted(values))        
        self.ui.lbAttrValue.setText("AttrValue ({0})".format(self.ui.cbAttrValue.count()))        

    @Slot()
    def getAttrValues(self):
        tags = self.soup.find_all(self.ui.cbTags.currentText(),                                     
                                     attrs={self.ui.cbAttributes.currentText():self.ui.cbAttrValue.currentText()}
                                     )
        values = set()
        for item in tags:
            values.add(item.get(self.ui.cbAttr2Extract.currentText()))
        self.ui.txtOutput.setPlainText("".join(str(item) + "\n" for item in values))

    @Slot()
    def loadWebSrc(self):        
        src = requests.get(self.ui.lnUrl.text())
        self.ui.txtSrc.setPlainText(src.text)        
        self.soup = BeautifulSoup(src.content, "html.parser")
        self.listTags()

    @Slot()
    def updateOutput(self):        
        results = self.soup.find_all(self.ui.cbTags.currentText(),                                     
                                     attrs={self.ui.cbAttributes.currentText():self.ui.cbAttrValue.currentText()}
                                     )
        self.ui.txtOutput.setPlainText("".join(str(item) + "\n" for item in results))

    @Slot()
    def getTagsText(self):        
        results = self.soup.find_all(self.ui.cbTags.currentText(),                                     
                                     attrs={self.ui.cbAttributes.currentText():self.ui.cbAttrValue.currentText()}
                                     )
        self.ui.txtOutput.setPlainText("".join(str(item.text.strip()) + "\n" for item in results))    

    @Slot()
    def loadLinks(self):        
        base_url = self.ui.lnUrl.text().rpartition("/")[0]
        links = self.ui.txtOutput.toPlainText().splitlines()
        self.ui.cbLinks.clear()
        for item in links:            
            self.ui.cbLinks.addItem(base_url + item)

    @Slot()
    def loadLink(self):        
        src = requests.get(self.ui.cbLinks.currentText())
        self.ui.txtSrc.setPlainText(src.text)
        self.soup = BeautifulSoup(src.content, "html.parser")
        self.listTags()

    
    @Slot()
    def loadRegExp(self):                
        self.ui.lnRegExp.setText(self.ui.cbLoadedRegExp.currentText())
        self.ui.btRegExp.click()        

    @Slot()
    def submitTable(self):
        self.model.database().transaction()
        if self.model.submitAll():
            self.model.database().commit()
        else:
            self.model.database().rollback()
            QMessageBox.warning(self, "Cached Table",
                                "The database reported an error: %s" % self.model.lastError().text())
    

    @Slot()
    def clearTable(self):
        db_handler.deleteTableEntries("results")        
        self.model.select()
    
    @Slot()
    def updateMiDiaResults(self):
        mi_dia.updateDBResults()        
        #self.model.setQuery(self.model.query())            
        self.loadTable()

    @Slot()
    def printMiDiaStats(self):
        self.ui.txtOutput.setPlainText("MiDia Stats\n")
        self.ui.txtOutput.moveCursor(QTextCursor.End)
        self.ui.txtOutput.insertPlainText("---------------------\n")
        stats = self.db.querytoString(mi_dia.getResultsByDate())        
        self.ui.txtOutput.moveCursor(QTextCursor.End)
        self.ui.txtOutput.insertPlainText(stats + "\n")
        
        self.ui.txtOutput.moveCursor(QTextCursor.End)
        self.ui.txtOutput.insertPlainText("Year | Reps\n")
        self.ui.txtOutput.insertPlainText("---------------------\n")
        stats = self.db.querytoString(mi_dia.getYears())
        self.ui.txtOutput.moveCursor(QTextCursor.End)
        self.ui.txtOutput.insertPlainText(stats + "\n")

        self.ui.txtOutput.moveCursor(QTextCursor.End)
        self.ui.txtOutput.insertPlainText("Month | Reps\n")
        self.ui.txtOutput.insertPlainText("---------------------\n")
        stats = self.db.querytoString(mi_dia.getMonths())
        self.ui.txtOutput.moveCursor(QTextCursor.End)
        self.ui.txtOutput.insertPlainText(stats + "\n")

        self.ui.txtOutput.moveCursor(QTextCursor.End)
        self.ui.txtOutput.insertPlainText("Day | Reps\n")
        self.ui.txtOutput.insertPlainText("---------------------\n")
        stats = self.db.querytoString(mi_dia.getDays())
        self.ui.txtOutput.moveCursor(QTextCursor.End)
        self.ui.txtOutput.insertPlainText(stats + "\n")

    @Slot()
    def getRascasInfo(self):
        self.ui.txtOutput.clear()
        links = rascas.getRascasLinks()
        #links = ["https://www.juegosonce.es/rasca-monopoly"]
        #links = ["https://www.juegosonce.es/rasca-sueldo-de-tu-vida-2020"]
        #links = ["https://www.juegosonce.es/rasca-super-cash-winner"]
        #links = ["https://www.juegosonce.es/rasca-ringo"]
        self.ui.txtOutput.insertPlainText(f"Rascas Links ({len(links)})\n")
        #self.ui.txtOutput.insertPlainText("---------------------\n")      
        #self.ui.txtOutput.moveCursor(QTextCursor.End)        
        #self.ui.txtOutput.insertPlainText("".join(item + "\n" for item in links))
        for item in links:
            #self.ui.txtOutput.insertPlainText(f"Link: {item} \n")
            #self.ui.txtOutput.moveCursor(QTextCursor.End)
            game_name = item.rsplit('/', 1)[-1]
            #self.ui.txtOutput.insertPlainText(f"Name: {game_name} \n")
            src = requests.get(item).content
            #self.ui.txtOutput.moveCursor(QTextCursor.End)
            prices = rascas.getPrecios(src.decode("utf-8"))
            #self.ui.txtOutput.insertPlainText(f"Precio/s : {prices} €\n")
            #self.ui.txtOutput.moveCursor(QTextCursor.End)
            tickets_amount = rascas.getTotalBoletos(str(src))
            #self.ui.txtOutput.insertPlainText(f"Total boletos : {tickets_amount}\n")
            prizes_list = rascas.getPremios(src)
            for index, table in enumerate(prizes_list):
                #for amount,prize in table:
                #    self.ui.txtOutput.moveCursor(QTextCursor.End)
                #    self.ui.txtOutput.insertPlainText(f"{amount} premios de {prize} €\n")
                #self.ui.txtOutput.moveCursor(QTextCursor.End)
                #self.ui.txtOutput.insertPlainText("---------------------\n")
                # DB Insertion            
                # game_info
                db = db_handler()                
                sql_query = f"INSERT INTO game_info (name, tickets_amount, price) VALUES('{game_name}','{tickets_amount[index]}','{prices[index]}')"
                db.exec_query(sql_query)

                sql_query = f"select id from game_info where name='{game_name}' and price='{prices[index]}'"
                print(sql_query)
                query_result = db.exec_query(sql_query)
                query_result.first()
                if query_result.isValid():
                    game_id = query_result.value('id')
                    # prizes
                    for amount,prize in table:
                    #    self.ui.txtOutput.moveCursor(QTextCursor.End)
                    #    self.ui.txtOutput.insertPlainText(f"{amount} premios de {prize} €\n")
                        sql_query = f"INSERT INTO prizes VALUES('{game_id}','{amount}','{prize}')"
                        db.exec_query(sql_query)
                


            
        

if __name__ == "__main__":
#    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
#    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication([])
    widget = WebScrapper()
    widget.show()
    sys.exit(app.exec())
