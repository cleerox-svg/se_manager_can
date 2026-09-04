SF_OPPORTUNITY_URL_TEMPLATE = "https://okta.lightning.force.com/lightning/r/Opportunity/{}/view"

def opportunity_url(opportunity_id):
    if not opportunity_id:
        return None
    return SF_OPPORTUNITY_URL_TEMPLATE.format(opportunity_id)
