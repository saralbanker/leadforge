# WhatsApp-Auto: Operator Runbook (Daily Solo Workflow)

## 1. Daily Operating Protocol

As a solo operator, your goal is to dispatch **20 to 25 highly targeted WhatsApp messages per day in under 10 minutes** during peak business hours.

### Prime Sending Windows (Indian Standard Time - IST)
- **Morning Window**: **10:30 AM – 1:00 PM IST** (Owners have reviewed morning factory dispatches and are at their desks).
- **Afternoon Window**: **3:30 PM – 5:30 PM IST** (Post-lunch lull before evening production reconciliation).
- **Do Not Send**: Before 9:30 AM, after 7:00 PM, or on Sundays.

---

## 2. Step-by-Step Daily Dispatch Routine

### Step 1: Launch the Local Queue
Run the queue manager command from terminal:
```bash
python3 -m foundation.queue_manager --daily-limit 25
```
This loads up to 25 verified, uncontacted Ahmedabad manufacturing leads from the database.

### Step 2: Review and Click Link
For each contact, the tool displays:
```text
============================================================
[1/25] Contact: BEENA ENGINEERING WORKS (Vatva GIDC)
Phone: +91 98250 12345
Message:
Hello Sir, noticed BEENA ENGINEERING WORKS manufactures industrial valves in Vatva GIDC.

When repeat orders come in on WhatsApp or phone, does your staff have to re-type those items into Tally by hand?

We built a simple tool for Ahmedabad manufacturers that pushes WhatsApp orders directly into Tally without re-typing.

Can I share a 30-second demo video here?

Saral Banker
Orvion, Ahmedabad
============================================================
Open Link: [https://web.whatsapp.com/send?phone=919825012345&text=...]
```

### Step 3: Send in WhatsApp Web / Desktop
1. Click the link (or press `[Enter]` if running with auto-browser opening).
2. WhatsApp Web opens with the contact's chat and the text already in the message box.
3. Verify the company name and click **Send** (or press Enter).
4. Mark status in the terminal:
   - Press `[s]` for `SENT` (default).
   - Press `[k]` for `SKIP` (e.g. if the number shows as invalid or personal DP is non-business).
   - Press `[n]` for `NOT_ON_WHATSAPP`.

---

## 3. Playbook for Inbound WhatsApp Replies

Because response rates on WhatsApp are 10x–20x higher than email, expect 3 to 6 replies per 25 messages sent.

### Scenario A: Prospect says *"Yes"*, *"Share"*, *"Send video"*, or *"Bhejo"*
- **Response**: Send the demo video link or 30-second screen recording immediately.
- **Follow-up Text**:
  > *"Here is the 30-second preview Sir: [Link]. It reads the WhatsApp message and creates a sales order voucher in Tally with one click. Do you currently use Tally Prime at your Vatva unit?"*

### Scenario B: Prospect asks *"How much does it cost?"* or *"Price?"*
- **Response**:
  > *"We charge a flat one-time setup fee between ₹15,000 and ₹25,000 depending on your voucher format—no monthly subscription. We are based nearby in Ellisbridge; I can drop by your office for 10 minutes this Friday to show a live demo on your test company data if you like."*

### Scenario C: Prospect says *"Not interested"*, *"No"*, or *"Nathi joiye"*
- **Response**:
  > *"Understood Sir, thank you for your time. Have a profitable quarter ahead!"*
- Mark as `OPT_OUT` in the database so they are never messaged again.

---

## 4. Troubleshooting & Error Recovery

| Issue | Root Cause | Solution |
| :--- | :--- | :--- |
| **"Phone number shared via url is invalid"** | Landline number (e.g. STD code 079) or incorrect digits scraped from site | The phone normalizer flags numbers not starting with 6, 7, 8, or 9. Press `[n]` to mark `NOT_ON_WHATSAPP`. |
| **WhatsApp Web takes long to load** | Browser cache or session expired | Open `web.whatsapp.com` directly in browser, re-link QR code, then continue queue. |
| **Duplicate company in queue** | Different subsidiaries or scraping runs | Database enforces `UNIQUE(normalized_phone)`. If detected, mark duplicate as `SKIP`. |
