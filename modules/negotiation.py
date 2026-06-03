"""
modules/negotiation.py
──────────────────────
Negotiation Script Generator.

For each upcoming renewal (insurance, credit card fee, internet, etc.)
already detected by the Life Event Engine, generates a ready-to-use
retention phone script with competitor quotes filled in.

Returns the same alert list passed in, with a `script` field added
to each insurance and credit_card_fee alert.
"""

SCRIPTS = {
    "insurance": """\
Hi, I'm calling about my {event_name} renewal.

I've been a customer with {current_provider} for some time and I've received \
a quote from {competitor} for ${est_new_premium:,}/year — that's a saving of \
about ${saving:,} on my current premium of ${current_premium:,}.

Before I make a decision, I wanted to give {current_provider} the opportunity \
to match or improve on that offer.

Is there anything you can do on the renewal price?

[If they ask for the competitor quote: Yes, I have a quote from {competitor} \
for ${est_new_premium:,} for equivalent cover.]

[If they offer a discount: Can you confirm that in writing/by email?]

[If they can't match: Thank you, I'll need to proceed with the switch.]""",

    "credit_card_fee": """\
Hi, I'm calling about my {card} annual fee of ${annual_fee:,} which is \
coming up for renewal.

I've been reviewing my credit cards and I'm considering cancelling due to \
the annual fee. Before I do, I wanted to check — is there a retention offer \
available? Sometimes that's a fee waiver or bonus points.

[If they offer something: What are the terms? Can you confirm that today?]

[If they offer bonus points: How many points, and when will they be credited?]

[If they offer nothing: In that case I'd like to proceed with cancelling \
the card. Can you confirm the cancellation process?]

Note: If cancelling, redeem all points first and check if a no-annual-fee \
product switch is available instead.""",
}


def add_negotiation_scripts(alerts: list[dict]) -> list[dict]:
    """
    Add a `script` field to each alert that has a negotiation angle.
    Mutates in place, returns the same list.
    """
    for alert in alerts:
        atype = alert.get("alert_type", "")

        if atype == "insurance":
            template = SCRIPTS["insurance"]
            script = template.format(
                event_name=alert.get("event_name", "insurance policy"),
                current_provider=alert.get("current_provider", "your insurer"),
                competitor=alert.get("competitor", "a competitor"),
                est_new_premium=alert.get("est_new_premium", 0),
                saving=alert.get("estimated_value", 0),
                current_premium=alert.get("current_premium", 0),
            )
            alert["script"] = script

        elif atype == "credit_card_fee":
            template = SCRIPTS["credit_card_fee"]
            script = template.format(
                card=alert.get("current_provider", "your card"),
                annual_fee=alert.get("current_premium", 0),
            )
            alert["script"] = script

        else:
            alert["script"] = ""

    return alerts
