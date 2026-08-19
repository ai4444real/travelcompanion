# Compagno di viaggio AI — Specifica MVP

## 1. Obiettivo

Realizzare un assistente personale AI che aiuti l’utente a **mantenere nel tempo gli impegni, le intenzioni e le cose che vorrebbe fare**, senza trasformarsi in un task manager tradizionale o in un sistema di reminder rigido.

L’interazione principale avviene tramite **conversazione**.

L’utente parla o scrive normalmente.  
Il sistema:

1. comprende ciò che l’utente vuole fare;
2. mantiene autonomamente uno stato strutturato;
3. individua scadenze, tensioni, conflitti e rischi;
4. apre una conversazione quando ritiene utile farlo;
5. aggiorna lo stato sulla base di ciò che viene deciso;
6. verifica periodicamente come stanno andando le cose.

Principio centrale:

> L’utente non deve amministrare il sistema. Deve poter parlare della propria vita; è il sistema che mantiene il modello necessario per seguirla.

---

# 2. Cosa NON è

L’MVP non deve diventare:

- un nuovo calendario;
- un nuovo Todoist;
- un sistema di project management;
- una dashboard piena di priorità e categorie;
- un habit tracker;
- un sistema di gamification;
- un motore che decide autonomamente cosa deve fare l’utente;
- un coach prescrittivo;
- un sistema che manda continuamente reminder.

Il suo valore non è **registrare task**.

Il suo valore è **mantenere nel tempo una conversazione coerente sulle cose che contano per l’utente**.

---

# 3. Principio di funzionamento

Il ciclo fondamentale è:

**ascolta → comprende → registra → osserva → individua tensioni → discute → aggiorna → continua a osservare**

Esempio:

**Utente**

> Voglio rifare la lezione X entro il 30. Ci metto almeno un giorno.

Il sistema registra l’intenzione e confronta questa nuova informazione con ciò che già conosce.

Se emerge un conflitto:

**Sistema**

> La prossima settimana avevamo anche previsto di finire il libro X. Preferisci dare priorità alla lezione?

**Utente**

> Sì.

**Sistema**

> Ok. Il libro rispetto alle altre cose dove lo mettiamo?

**Utente**

> Tra B e C.

Il sistema modifica autonomamente il proprio stato.

L’utente **non deve successivamente entrare in una schermata per correggere priorità, date o relazioni**.

---

# 4. Filosofia dell’MVP

## 4.1 Conversazione prima della struttura

Non viene definita a priori una tassonomia complessa.

Non devono esistere obbligatoriamente categorie come:

- priorità 1–5;
- urgente/importante;
- personale/professionale;
- habit/task/goal/project;
- classe A/B/C.

Se queste distinzioni servono internamente, possono essere inferite e memorizzate dal sistema.

L’utente deve poter dire:

> Devo assolutamente inviare le fatture entro il 20 perché altrimenti blocchiamo gli incassi.

oppure:

> Questo libro mi piacerebbe leggerlo, ma non succede niente se ci metto sei mesi.

Sono informazioni molto più significative di una generica priorità numerica.

---

## 4.2 L’importanza è negoziata

Il sistema non assegna arbitrariamente l’importanza.

La costruisce attraverso la conversazione.

Esempio:

> Se le fatture slittano di due giorni è un problema?

> Sì, perché ritardiamo gli incassi.

Questa informazione modifica il comportamento futuro del sistema.

Analogamente:

> Voglio leggere questo libro.

può inizialmente significare:

> quando capita.

Successivamente:

> Devo averlo finito entro il 20 ottobre perché ne discuteremo a un meeting.

Lo stesso elemento cambia quindi importanza e urgenza **senza che l’utente debba riclassificarlo manualmente**.

---

# 5. Tipologie concettuali

Il sistema deve essere capace di gestire almeno quattro grandi famiglie, senza obbligare l’utente a conoscerle o selezionarle.

### Impegni

Cose che devono essere fatte e che possono avere conseguenze concrete.

Esempi:

- inviare le fatture il 20;
- fare i richiami il martedì;
- preparare una lezione entro una certa data.

### Routine / mantenimento

Comportamenti che l’utente vuole mantenere con una certa frequenza o quantità.

Esempi:

- correre tre volte a settimana;
- correre almeno 15 km;
- meditare ogni giorno.

### Introduzioni / cambiamenti

Cose che l’utente vuole iniziare o reinserire nella propria vita.

Esempi:

- riprendere la meditazione;
- ricominciare a suonare il basso.

### Possibilità / backlog

Cose desiderabili ma senza necessariamente un impegno temporale.

Esempi:

- leggere un libro;
- studiare un argomento;
- rifare una vecchia lezione;
- approfondire qualcosa.

Queste famiglie servono al ragionamento interno, non necessariamente all’interfaccia.

---

# 6. Modello interno minimo

Il sistema deve mantenere un archivio strutturato.

**L’archivio viene aggiornato principalmente dall’AI, non direttamente dall’utente.**

Ogni elemento può contenere, quando disponibili:

- identificativo;
- descrizione sintetica;
- stato;
- eventuale scadenza;
- eventuale frequenza;
- eventuale quantità obiettivo;
- stima del tempo necessario;
- avanzamento conosciuto;
- importanza percepita;
- conseguenze del mancato completamento;
- flessibilità;
- relazioni con altri elementi;
- ordine relativo rispetto ad altre intenzioni;
- motivazione o contesto;
- data dell’ultima verifica;
- livello di affidabilità delle informazioni;
- eventuali note utili al ragionamento futuro.

Non tutti i campi devono essere obbligatori.

Il sistema deve tollerare informazioni incomplete.

---

# 7. Stato degli elementi

Ogni elemento deve poter essere almeno:

- attivo;
- completato;
- sospeso;
- abbandonato;
- in attesa;
- non ancora pianificato.

Il sistema deve distinguere, per esempio:

> “Non ho meditato oggi”

da:

> “Per questo mese sospendiamo la meditazione.”

Nel secondo caso non deve continuare a richiamarla come se fosse un fallimento.

---

# 8. Conversazione e memoria

Ogni messaggio dell’utente deve poter produrre tre risultati distinti:

### 1. Nessun cambiamento

Conversazione normale.

### 2. Aggiornamento dello stato

Esempio:

> Il libro mettilo dopo B ma prima di C.

Il sistema modifica l’archivio.

### 3. Necessità di chiarimento

Il sistema può chiedere informazioni quando servono realmente per evitare un’interpretazione sbagliata.

Esempio:

> Voglio finirlo presto.

Possibile domanda:

> “Presto” significa che hai una data reale oppure semplicemente che vuoi dargli più spazio?

Le domande devono essere **funzionali a una decisione**, non finalizzate a riempire campi del database.

---

# 9. Conferma degli aggiornamenti

Normalmente gli aggiornamenti semplici non richiedono una procedura formale.

Esempio:

> Per ora sospendiamo il basso.

Risposta sufficiente:

> Ok, lo metto in pausa.

Per modifiche più rilevanti il sistema può esplicitare ciò che sta per cambiare.

Esempio:

> Quindi diamo precedenza alla preparazione della lezione e facciamo slittare il libro. Corretto?

L’obiettivo è evitare sia:

- continui popup di conferma;

sia:

- modifiche importanti basate su interpretazioni fragili.

---

# 10. Monitoraggio

Il sistema deve effettuare verifiche periodiche dello stato.

Il monitoraggio non consiste nel chiedere ogni giorno:

> Hai fatto X?  
> Hai fatto Y?  
> Hai fatto Z?

Deve decidere **quando una domanda produce valore**.

---

# 11. Quando intervenire

La probabilità e l’intensità dell’intervento devono dipendere dal contesto conosciuto.

Esempi.

### Fatture

Scadenza vicina + conseguenza economica importante.

Il sistema deve intervenire presto e con maggiore decisione.

### Libro senza scadenza

Nessuna conseguenza concreta.

Può rimanere silenzioso per settimane.

### Libro necessario per un meeting

La stessa attività diventa improvvisamente molto più rilevante.

Il comportamento del sistema deve adeguarsi.

---

# 12. Individuazione delle tensioni

Una funzione fondamentale è rilevare situazioni che **potrebbero diventare problematiche prima che lo diventino**.

Esempio:

- libro da completare entro 10 giorni;
- stima iniziale: 5 giornate;
- 3 giornate già fatte;
- stima residua teorica: 2 giornate.

Il sistema non deve necessariamente concludere:

> Sei in ritardo.

Deve invece poter dire:

> Vuoi finirlo entro il 30. Mancano dieci giorni; avevamo stimato cinque giornate e ne hai già fatte tre. Come ti senti rispetto alla possibilità di finirlo?

---

# 13. La percezione dell’utente fa parte dei dati

La risposta dell’utente modifica la valutazione.

### Caso A

> Sono tranquillo. Due giornate le trovo sicuramente.

Il sistema registra una situazione considerata sotto controllo.

Non deve necessariamente fare altro.

### Caso B

> In realtà me ne servono almeno quattro.

Il sistema aggiorna la stima e rivaluta la fattibilità.

### Caso C

> Non ce la farò mai.

Il sistema apre una conversazione decisionale.

Per esempio:

- cambiare la scadenza;
- ridurre l’obiettivo;
- liberare tempo;
- rinunciare temporaneamente ad altro;
- abbandonare l’obiettivo.

Non deve scegliere automaticamente.

---

# 14. Rinegoziazione

Una delle funzioni principali del prodotto è permettere di **rinegoziare gli accordi con se stessi**.

Il sistema non deve considerare automaticamente uno scostamento come fallimento.

Esempio:

> Questa settimana volevo correre tre volte ma non ce la faccio.

Possibile risposta:

> Va bene. È una settimana eccezionale oppure vuoi rivedere l’obiettivo delle tre corse?

Questo permette di distinguere:

- eccezione;
- nuovo pattern;
- obiettivo diventato irrealistico;
- priorità temporaneamente cambiata.

---

# 15. Gestione dei conflitti

Quando viene aggiunto un nuovo impegno significativo, il sistema deve valutare cosa viene spostato.

Esempio:

> Voglio preparare questa nuova lezione entro venerdì. Mi serve una giornata.

Se il carico già conosciuto è alto:

> Possiamo farlo, ma significa probabilmente rinunciare a una delle cose che avevamo previsto. Vuoi dare precedenza alla lezione rispetto al libro?

Il sistema non deve fingere che il tempo sia infinito.

---

# 16. Priorità relative

Le priorità possono essere espresse anche in forma relativa.

Esempio:

> Il libro è meno importante di B ma più importante di C.

Questa relazione deve poter essere memorizzata senza obbligare l’utente a trasformarla in un numero.

Internamente il sistema può derivare un ordinamento se necessario.

---

# 17. Stima e capacità

Il sistema deve poter ragionare almeno grossolanamente su:

- tempo necessario;
- tempo residuo;
- frequenza desiderata;
- avanzamento;
- scadenza;
- numero di occasioni rimaste.

Non serve un sofisticato motore matematico nell’MVP.

Serve abbastanza ragionamento da poter individuare incongruenze evidenti.

---

# 18. Check-in

Il sistema deve poter avviare autonomamente una conversazione.

Esempi:

> Questa settimana volevi correre tre volte e siamo a venerdì senza corse registrate. È ancora realistico?

> Sono dieci giorni che non parliamo del basso. È ancora qualcosa che vuoi reinserire oppure per ora lo lasciamo fermo?

> La preparazione della lezione è prevista entro quattro giorni. L’ultima volta mi avevi detto che serviva ancora una giornata. Siamo ancora tranquilli?

I check-in devono essere selettivi.

---

# 19. Frequenza dei controlli

Per l’MVP è sufficiente un processo schedulato che, a intervalli definiti, analizzi lo stato.

Possibile impostazione iniziale:

- controllo generale giornaliero;
- valutazione settimanale più ampia.

Il controllo giornaliero **non implica un messaggio giornaliero**.

Il processo deve poter concludere:

> Non c’è niente di utile da dire.

Questo è un risultato valido.

---

# 20. Motore di decisione per il check-in

A ogni controllo il sistema deve chiedersi:

1. È cambiato qualcosa?
2. Si avvicina una scadenza?
3. L’andamento è compatibile con l’obiettivo?
4. Mancano informazioni importanti?
5. È passato molto tempo dall’ultima verifica?
6. L’elemento è abbastanza importante da giustificare un’interruzione?
7. C’è una decisione concreta che l’utente potrebbe prendere?

Solo se il valore atteso della conversazione è sufficiente viene inviato un messaggio.

---

# 21. Tono

Il sistema deve comportarsi come **un compagno di viaggio competente**, non come un controllore.

Deve poter essere:

- attento;
- pragmatico;
- curioso;
- capace di ricordare;
- capace di far emergere incoerenze;
- rispettoso delle eccezioni;
- non giudicante;
- non eccessivamente accomodante.

Non deve essere:

- paternalistico;
- colpevolizzante;
- motivazionale a tutti i costi;
- ossessivo;
- passivo.

Esempio corretto:

> Erano tre corse e questa settimana ne hai fatta una. È stata semplicemente una settimana particolare o dobbiamo capire se tre sta diventando troppo?

Non:

> Non preoccuparti! Una settimana difficile capita a tutti! 💪

e nemmeno:

> Obiettivo fallito: 1/3.

---

# 22. Archivio e interfaccia

L’archivio deve esistere, ma **non è l’interfaccia primaria**.

L’utente deve avere comunque una pagina semplice dalla quale poter:

- vedere cosa il sistema considera attivo;
- vedere ciò che ha capito;
- vedere scadenze e stato;
- correggere errori;
- sospendere;
- eliminare;
- eventualmente modificare direttamente qualcosa.

Questa pagina è una **console di ispezione e sicurezza**, non il luogo quotidiano di gestione.

---

# 23. Inserimento di una nuova cosa

Flusso tipico:

**Utente**

> Vorrei ricominciare a meditare tutti i giorni.

Il sistema potrebbe chiedere:

> È una cosa che vuoi davvero rendere stabile oppure per ora vuoi semplicemente provare a reinserirla?

Dopo la risposta aggiorna lo stato.

Non deve aprire un form con:

- nome;
- categoria;
- priorità;
- frequenza;
- progetto;
- colore;
- tag.

---

# 24. Aggiornamento tramite linguaggio naturale

Devono funzionare frasi come:

> Sospendi la meditazione fino a settembre.

> Ho finito il libro.

> Il libro in realtà è diventato urgente.

> Questa settimana ho corso solo due volte ma va bene così.

> Non voglio più fare questa cosa.

> La lezione richiederà due giorni, non uno.

> Ricordamela meno spesso.

> Questa cosa è diventata molto più importante.

Il sistema modifica autonomamente i dati corrispondenti.

---

# 25. Nessuna integrazione nell’MVP

La prima versione deve funzionare **senza Google Calendar, Notion, Google Tasks o altre sorgenti esterne**.

Questa è una scelta deliberata.

Prima si verifica che il comportamento del compagno di viaggio produca valore.

Solo successivamente si aggiungono integrazioni quando emerge un caso concreto.

---

# 26. Architettura predisposta alle integrazioni

Pur non implementandole subito, il sistema deve essere progettato in modo che in futuro sia possibile aggiungere adapter.

Esempio:

**Google Calendar → adapter → eventi normalizzati**

**Notion → adapter → elementi normalizzati**

**Google Tasks → adapter → attività normalizzate**

Il core non deve conoscere le peculiarità delle singole sorgenti.

Le integrazioni devono poter fornire **evidenze** al sistema.

Esempio futuro:

> Nel calendario compare una corsa di 50 minuti.

Il sistema può usarla come segnale che la corsa è avvenuta.

---

# 27. Distinzione tra fatti e inferenze

Il sistema deve distinguere tra:

### Fatto esplicito

> Ho corso stamattina.

### Evidenza

> Esiste nel calendario un evento “corsa”.

### Inferenza

> Probabilmente hai corso.

Le inferenze non devono essere registrate come fatti certi senza una soglia adeguata.

Quando serve:

> Vedo una corsa nel calendario stamattina: confermi che l’hai fatta?

---

# 28. Audit minimo

Ogni modifica significativa allo stato dovrebbe avere:

- timestamp;
- origine;
- eventuale messaggio che l’ha provocata;
- valore precedente;
- nuovo valore.

Non serve mostrare questo log normalmente all’utente.

Serve per:

- debug;
- correzioni;
- comprensione degli errori dell’AI;
- eventuale rollback.

---

# 29. AI e dati strutturati

L’LLM non deve essere l’unico deposito della memoria.

La conversazione viene interpretata dall’AI, ma lo stato significativo deve essere salvato in forma strutturata.

Schema concettuale:

**messaggio → LLM → proposta di modifica → validazione → database**

L’AI deve poter leggere lo stato aggiornato prima di produrre decisioni rilevanti.

---

# 30. Azioni dell’AI

L’AI deve poter produrre almeno queste azioni strutturate:

- create_item
- update_item
- complete_item
- suspend_item
- abandon_item
- reorder_item
- add_relation
- update_estimate
- record_progress
- record_user_assessment
- request_clarification
- send_checkin
- no_action

Il testo conversazionale e l’azione sui dati sono due risultati distinti della stessa elaborazione.

---

# 31. Sicurezza contro modifiche arbitrarie

Il modello può inferire informazioni, ma non deve inventare decisioni dell’utente.

Esempio:

> Non penso di riuscire a leggere il libro.

Non equivale automaticamente a:

`status = abandoned`

Deve eventualmente chiedere:

> Vuoi rinunciarci oppure semplicemente spostarlo?

---

# 32. Componenti tecnici minimi

Una possibile implementazione MVP comprende:

### Backend

API applicativa.

### Database

Archivio di:

- elementi;
- stato;
- relazioni;
- progressi;
- check-in;
- log delle modifiche.

### LLM layer

Responsabile di:

- comprensione del linguaggio;
- estrazione delle modifiche;
- ragionamento conversazionale;
- generazione delle domande.

### Monitor

Processo schedulato che analizza periodicamente gli elementi attivi.

### Interfaccia

Web app responsive/PWA utilizzabile da telefono.

Funzioni iniziali:

- chat;
- visualizzazione stato;
- correzione manuale minima.

---

# 33. Separazione tra motore e modello AI

La logica fondamentale non deve dipendere completamente da un prompt gigantesco.

Il codice deve gestire direttamente almeno:

- persistenza;
- date;
- scadenze;
- ricorrenze;
- calcoli temporali;
- stato;
- cronologia;
- scheduler;
- esecuzione delle azioni.

L’AI gestisce soprattutto:

- interpretazione;
- ambiguità;
- confronto tra intenzioni;
- dialogo;
- valutazione contestuale.

---

# 34. Memoria conversazionale

Non è necessario inviare tutta la cronologia di tutte le conversazioni a ogni richiesta.

Il contesto del modello dovrebbe essere costruito usando:

1. messaggi recenti;
2. stato strutturato rilevante;
3. eventuali decisioni passate pertinenti;
4. informazioni generali sull’utente necessarie alla conversazione.

L’archivio strutturato rappresenta la memoria operativa principale.

---

# 35. MVP: cosa deve funzionare davvero

La prima versione è riuscita se permette di fare bene questi casi.

### Caso 1 — Aggiunta

> Voglio correre tre volte alla settimana.

Il sistema comprende, eventualmente chiarisce e registra.

### Caso 2 — Conversazione sulla priorità

> Voglio anche rifare la lezione entro venerdì.

Il sistema individua il possibile conflitto con altre cose importanti e ne discute.

### Caso 3 — Aggiornamento automatico

> Il libro mettilo dopo B.

Lo stato viene aggiornato senza aprire schermate.

### Caso 4 — Progressione

> Del libro ho fatto tre delle cinque giornate previste.

Il sistema registra l’avanzamento.

### Caso 5 — Intercettazione

La scadenza si avvicina e il margine diminuisce.

Il sistema apre autonomamente una conversazione.

### Caso 6 — Rinegoziazione

> Non ce la farò.

Il sistema aiuta a scegliere cosa cambiare.

### Caso 7 — Sospensione

> Per questo mese lasciamo perdere il basso.

Il sistema smette di sollecitare il basso.

### Caso 8 — Silenzio intelligente

Non succede nulla che meriti attenzione.

Il sistema non manda niente.

---

# 36. Cose esplicitamente fuori dall’MVP

Non implementare inizialmente:

- Google Calendar;
- Notion;
- Google Tasks;
- Todoist;
- dati sportivi;
- email;
- scheduling automatico dettagliato;
- calendar blocking;
- riconoscimento vocale avanzato;
- notifiche sofisticate;
- app Android/iOS native;
- gamification;
- statistiche elaborate;
- grafici;
- sistemi di produttività predefiniti;
- tassonomie complesse;
- multiutente.

Devono poter essere aggiunti successivamente senza cambiare il concetto di base.

---

# 37. Prima evoluzione possibile

Le integrazioni verranno introdotte solo quando permettono di evitare una domanda o una registrazione manuale.

Regola:

> Se il sistema può sapere qualcosa in modo affidabile da una sorgente già esistente, non dovrebbe chiedere all’utente di registrarla nuovamente.

Esempio:

prima:

> Hai corso oggi?

dopo integrazione:

> Vedo una corsa stamattina. Tutto regolare, quindi non ti disturbo.

---

# 38. Criterio principale di successo

Il successo dell’MVP non si misura dal numero di task registrati.

La domanda principale è:

> **Dopo alcune settimane l’utente continua spontaneamente a parlare con il sistema perché sente che gli sta realmente togliendo carico mentale?**

In particolare deve diminuire:

- il bisogno di ricordarsi cosa aveva deciso;
- il bisogno di mantenere manualmente liste;
- il rischio di accorgersi troppo tardi di un problema;
- la necessità di ricostruire ogni volta priorità e contesto.

---

# 39. Test decisivo dell’MVP

Dopo 3–4 settimane dovrebbe essere possibile chiedere:

> Come stanno andando le cose?

e ricevere una risposta coerente del tipo:

> Le fatture sono sotto controllo.  
> La corsa sta rispettando abbastanza bene le tre volte settimanali.  
> La meditazione è sospesa fino a settembre.  
> Il libro X è diventato più critico perché il meeting si avvicina: mancano due sessioni previste e otto giorni.  
> Il basso invece è rimasto nel backlog e per ora non vedo motivo di riportarlo in primo piano.

Se il sistema è capace di rispondere così **senza che l’utente abbia dovuto mantenere manualmente un secondo mondo parallelo di dati**, l’MVP sta facendo il suo lavoro.

---

# 40. Principio guida finale

Quando nasce un dubbio progettuale, usare questa domanda:

> **Questa funzione permette al compagno di viaggio di capire meglio, ricordare meglio, intercettare prima un problema o ridurre il lavoro amministrativo dell’utente?**

Se la risposta è no, probabilmente non appartiene all’MVP.