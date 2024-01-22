from PySide6.QtSql import QSqlDatabase, QSqlQuery

class db_handler(QSqlDatabase):
    def init_db(self):
        self.db = QSqlDatabase.addDatabase("QSQLITE")        
        self.db.setDatabaseName("juegosOnce.db")
        self.db.setNumericalPrecisionPolicy
        if self.db.isValid():
            print("Valid SqlDataBase")
        else:
            print("NON Valid SqlDataBase")

        self.db.open()
        if self.db.isOpen():
            print("Opened SqlDataBase")
        else:
            print("Error opening SqlDataBase")
        
    
    def tables(self):
        return self.db.tables()

    #  def __del__(self):
        #self.db.close()

    def querytoString(self,query):
        result = ""
        if query is not None:
            while query.next():
                fieldId = 0        
                while query.value(fieldId):                
                    result = result + str(query.value(fieldId)) + " | "
                    fieldId = fieldId + 1 
                result = result + "\n"    
        return result

    def exec_query(self,sql_query):
        query = QSqlQuery()        
        #print("Executing SQL query : ", sql_query)
        if not query.exec_(sql_query):
            #print("Failed to query database : " + sql_query)
            return
        else:
            # print("lastError : ", self.db.lastError().databaseText())
            return query

    def deleteTableEntries(self,tableName):
        self.exec_query("DELETE FROM " + tableName)
        
