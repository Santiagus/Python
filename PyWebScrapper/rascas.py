import locale
import datetime
import re
from tokenize import Double
import requests
from db_handler import db_handler
from bs4 import BeautifulSoup

def getRascasLinks():    
    rascas_url = "https://www.juegosonce.es/rascas-todos"
    base_url = "https://www.juegosonce.es"
    src = requests.get(rascas_url)
    soup = BeautifulSoup(src.content, "html.parser")
        
    tags = soup.find_all('a',attrs={'class':'informacionrasca'})
    links = []
    for item in tags:
        links.append(base_url + item.get('href'))
    #links.append(base_url + tags[0].get('href'))
    #print("Rasca Links: ", links)
    return links

def getNumbers(self):
        pattern = "\d+[.,]?\d*"
        string = self.ui.txtSrc.toPlainText()
        result = re.findall(pattern,string)
        #print(result)
        self.ui.txtOutput.setPlainText("".join(x + "\n" for x in result))
        self.ui.txtSrc.find(pattern)

def getTotalBoletos(src):
    pattern = "Premios por cada serie de boletos de (\d+\.?\d+\.?\d+\.?)"    
    result = re.findall(pattern,src)    
    ret_values = []
    for i in result:
        ret_values.append(i.replace('.', '').replace(',', '.'))
    return ret_values

def getPrecios(src):    
    pattern = "Precio: ([\d, €-]*)"
    result = re.findall(pattern,src)[0]
    pattern = "(\d*[.,]?\d*[.,]?\d+)"
    result = re.findall(pattern,result)
    ret_values = []
    for i in result:
        ret_values.append(i.replace('.', '').replace(',', '.'))
    #print("Precios : ", result)
    return ret_values

def getPremios(src):
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
    # Get web source
    #src = requests.get(url)
    soup = BeautifulSoup(src, "html.parser")
    tags = soup.find_all('ul',attrs={'class':'premiosrascas'})
    #pattern = "\d*[.,]?\d*[.,]?\d+"
    #pattern = "(\d+[.,]?\d*)(?!\d* años)"
    #pattern = "\d*[.,]?\d+[.,]?\d*"
    pattern = "(\d*[.,]?\d+[.,]?\d*)(?!\d* años)"
    years_pattern = "(\d*) años"
    prizes_list = []
    for item in tags: # Usually 1 but up to 3        
        values = re.findall(pattern,str(item))        
        years_multiplier = re.findall(years_pattern,str(item))
        if years_multiplier:
            values[1] = str(float(values[1].replace('.', '').replace(',', '.')) * int(years_multiplier[0]))
        prizes = []
        while len(values)>1:            
            prizes.append([values.pop(0).replace('.', '').replace(',', '.'), values.pop(0).replace('.', '').replace(',', '.')])
        prizes_list.append(prizes)
    #print("Premios : ", prizes_list)
    return prizes_list

'''
def updateRascaPrizes():
    print("updateRascaPrizes")
    resultsDic = getDrawResults()  # {['22-02-2023':'08-11-1949'], ['22-02-2023':'08-11-1949']}    
    miDiaBataBaseID = 1    
    db = db_handler()
    for key in resultsDic:
        sqlQuery = f"INSERT INTO results VALUES ({miDiaBataBaseID},'{key}','{resultsDic[key]}')"
        #sqlQuery = sqlQuery[0: -1]        
        db.exec_query(sqlQuery)
'''