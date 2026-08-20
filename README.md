# Compagno di viaggio AI

MVP conversazionale che mantiene nel tempo impegni, intenzioni, routine e possibilità senza chiedere all’utente di amministrare un task manager.

## Cosa include

- chat in linguaggio naturale con interprete locale immediatamente utilizzabile;
- provider OpenAI opzionale tramite Responses API e output JSON strutturato;
- memoria operativa SQLite per elementi, relazioni, progressi e conversazioni;
- esecuzione validata delle azioni: l’AI propone, il dominio controlla e applica;
- audit prima/dopo per ogni modifica significativa;
- monitor selettivo per scadenze, avanzamento e verifiche rimaste in sospeso;
- silenzio intelligente quando non esiste una conversazione utile da aprire;
- console di ispezione e correzione manuale;
- interfaccia responsive installabile come PWA;
- API documentata automaticamente su `/docs`.

La specifica di prodotto completa è in [Compagno di viaggio AI — Specifica MVP.md](./Compagno%20di%20viaggio%20AI%20%E2%80%94%20Specifica%20MVP.md).

## Avvio locale

Richiede Python 3.11 o successivo.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Aprire <http://127.0.0.1:8000>.

Per impostazione predefinita l’app usa `AI_PROVIDER=local`: copre i flussi di accettazione dell’MVP e permette di provare persistenza, interfaccia e monitor senza una chiave esterna.

## Provider OpenAI

Impostare le variabili nell’ambiente usando `.env.example` come riferimento:

```text
AI_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5-mini
```

L’app non carica automaticamente `.env`, per evitare dipendenze e comportamenti impliciti. In PowerShell, per una sessione locale:

```powershell
$env:AI_PROVIDER='openai'
$env:OPENAI_API_KEY='...'
uvicorn app.main:app --reload
```

Il provider usa `store: false`; lo stato operativo resta nel database dell’app. Il modello è configurabile e il core non dipende dal provider.

## Test

```powershell
python -m pytest -q
```

I test coprono gli otto casi decisivi della specifica: aggiunta, conflitto, riordino relativo, avanzamento, intercettazione, rinegoziazione, sospensione e silenzio intelligente. È inoltre verificata la registrazione audit prima/dopo.

## Architettura

```text
messaggio
   ↓
interprete locale / OpenAI
   ↓ proposta strutturata
validatore ed esecutore azioni
   ↓
SQLite + audit
   ↑
monitor periodico → check-in solo sopra soglia
```

I confini principali sono:

- `app/ai.py`: interpretazione e adapter del provider AI;
- `app/domain.py`: validazione ed esecuzione delle azioni;
- `app/repository.py`: persistenza e audit;
- `app/monitor.py`: valutazione deterministica dei check-in;
- `app/main.py`: API e scheduler;
- `app/static/`: web app/PWA.

Le future integrazioni possono essere aggiunte come adapter che producono evidenze normalizzate, senza introdurre dettagli delle sorgenti nel core.

## Limiti deliberati dell’MVP

- singolo utente e nessuna autenticazione;
- nessuna integrazione esterna;
- i check-in compaiono nella PWA, senza notifiche push;
- l’interprete locale è un baseline deterministico, non sostituisce un LLM generale;
- nessuna app mobile nativa, gamification o pianificazione automatica dettagliata.

## Deployment sul VPS

Il deployment previsto usa `/opt/travel-companion`, un virtualenv isolato e il servizio `travel-companion.service`, in ascolto soltanto su `127.0.0.1:8100`.

```bash
cd /opt/travel-companion
sudo ./scripts/install-server.sh
```

Finché non viene aggiunta autenticazione, non pubblicare direttamente il servizio tramite reverse proxy. Per accedervi in sicurezza dal proprio computer:

```powershell
ssh -L 8100:127.0.0.1:8100 ubuntu@SERVER
```

Lasciare aperta la sessione e visitare <http://127.0.0.1:8100>.
