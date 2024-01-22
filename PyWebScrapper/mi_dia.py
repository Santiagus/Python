import locale
import datetime
import re
import requests
from db_handler import db_handler

from bs4 import BeautifulSoup

def getMiDiaResultsLinks():        
    # Get Urls
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
    day = 1
    month = 10
    year = 2020
    date = datetime.date(year, month, day)        
    links = list()
    while date < datetime.date.today():
        url = "https://www.juegosonce.es/historico-resultados-mi-dia-once-" + date.strftime("%B-%Y")
        links.append(url)
        if month == 12: 
            year = year + 1
        month = month % 12 + 1
        date = datetime.date(year, month, day)            
        
    return links


def getDrawResults():
    # Historic Results links    
    links = getMiDiaResultsLinks()
    historico = {}
    resultDates = list()
    drawDates = list()
    for url in links:
        print("Loading " + url)   
        # Get draw month/Year from url
        year = re.findall("\d+", url)[0]
        month = re.findall("-(\w+)-\d+", url)[0]
        src = requests.get(url) # Load web source
        drawDays = re.findall("span>(\d+)", str(src.content)) # Get draw Days
        # Get draw results
        soup = BeautifulSoup(src.content, "html.parser")
        #print("Filtering Tags")
        results = soup.find_all('span',attrs={'class':'fechaMD'})
        for item in results:
            #print("Founded result date :", item.text.strip())
            resultDates.append(item.text.strip())

        #locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
        dateFormat = "%d-%m-%Y"    
        for day in drawDays:
            drawDate = datetime.datetime.strptime(year+month+day, "%Y%B%d")                
            result = datetime.datetime.strptime(resultDates.pop(0).replace(" ", "."), "%d.%b%Y")

            historico [drawDate.strftime(dateFormat)] = result.strftime(dateFormat)
        #    print("Sorteo " + drawDate.strftime(dateFormat) + " Resultado " + result.strftime(dateFormat))
        
    return historico


def updateDBResults():
    print("updateDBResults")
    resultsDic = getDrawResults()  # {['22-02-2023':'08-11-1949'], ['22-02-2023':'08-11-1949']}    
    miDiaBataBaseID = 1    
    db = db_handler()
    for key in resultsDic:
        sqlQuery = f"INSERT INTO results VALUES ({miDiaBataBaseID},'{key}','{resultsDic[key]}')"
        #sqlQuery = sqlQuery[0: -1]        
        db.exec_query(sqlQuery)

def getResultsByDate():
    sqlQuery = "SELECT substr(result,7)||'-'||substr(result,4,2)||'-'||substr(result,1,2) as date FROM results order by date"
    db = db_handler()
    query = db.exec_query(sqlQuery)    
    return query

def getYears():
    sqlQuery = "SELECT substr(result,7) as year, count(id) as reps FROM results group by year order by reps DESC"
    db = db_handler()
    query = db.exec_query(sqlQuery)    
    return query

def getMonths():
    sqlQuery = "SELECT substr(result,4,2) as month, count(id) as reps FROM results group by month order by reps DESC"
    db = db_handler()
    query = db.exec_query(sqlQuery)    
    return query

def getDays():
    sqlQuery = "SELECT substr(result,1,2) as day, count(id) as reps FROM results group by day order by reps DESC"
    db = db_handler()
    query = db.exec_query(sqlQuery)    
    return query
