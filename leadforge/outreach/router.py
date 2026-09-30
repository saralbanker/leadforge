import hashlib
import re
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
from leadforge.config import BASE_DIR
from leadforge.outreach.cleaning import clean_company_name, shorten_company_name
from leadforge.utils import get_logger

logger = get_logger()


def select_template_variant(
    raw_template: Any,
    business_id: Optional[str] = None,
    salt: str = "",
) -> str:
    """Deterministically selects a template variant for a lead.

    - If raw_template is a dict with slots (e.g. 'middles'/'closings' or 'slots'):
      selects each slot independently with distinct salted SHA256 hashes and composes them.
    - If raw_template is a list, picks one deterministically using a salted SHA256 hash of business_id.
    - If raw_template is a plain string, returns it directly for backward compatibility.
    """
    if isinstance(raw_template, dict):
        # Case 1: Slot-based composition dictionary with middles/closings
        if "middles" in raw_template or "middle" in raw_template:
            middles = raw_template.get("middles") or raw_template.get("middle") or []
            closings = raw_template.get("closings") or raw_template.get("closing") or []

            mid_salt = f"{salt}_middle" if salt else "middle"
            cls_salt = f"{salt}_closing" if salt else "closing"

            selected_middle = select_template_variant(middles, business_id=business_id, salt=mid_salt)
            selected_closing = select_template_variant(closings, business_id=business_id, salt=cls_salt)

            tpl = raw_template.get("template")
            if tpl:
                out = tpl.replace("{middle}", selected_middle).replace("{closing}", selected_closing)
                return out
            else:
                parts = []
                if "{observation_hook}" not in selected_middle:
                    parts.append("{observation_hook}")
                if selected_middle:
                    parts.append(selected_middle)
                if selected_closing:
                    parts.append(selected_closing)
                return "\n\n".join(parts)

        # Case 2: Generic slot dictionary with a template
        elif "slots" in raw_template:
            slots_dict = raw_template["slots"]
            tpl = raw_template.get("template", "")
            replacements = {}
            for slot_name, slot_options in slots_dict.items():
                slot_salt = f"{salt}_{slot_name}" if salt else slot_name
                replacements[slot_name] = select_template_variant(slot_options, business_id=business_id, salt=slot_salt)
            out = tpl
            for slot_name, slot_val in replacements.items():
                out = out.replace(f"{{{slot_name}}}", slot_val)
            return out

        # Case 3: Dict with body_structure / body_structure_unverified wrapper
        elif "body_structure" in raw_template or "body_structure_unverified" in raw_template:
            body_raw = raw_template.get("body_structure_unverified") or raw_template.get("body_structure", "")
            return select_template_variant(body_raw, business_id=business_id, salt=salt or "body")

        return str(raw_template)

    elif isinstance(raw_template, list):
        if not raw_template:
            return ""
        if not business_id:
            return str(raw_template[0])
        # Deterministic index based on salted sha256 of business_id
        seed = f"{salt}:{business_id}" if salt else str(business_id)
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % len(raw_template)
        return str(raw_template[idx])
    elif isinstance(raw_template, str):
        return raw_template
    elif raw_template is None:
        return ""
    # str() on a dict or any other container yields a repr full of braces and
    # colons, which downstream .format_map() reads as format specifiers and
    # rejects with "Invalid format specifier" - a 500 per draft with a cause
    # that is not obvious from the message. Refuse loudly instead.
    logger.error(
        "Unsupported template type %s in copy config; expected str, list, or slot "
        "dict. Returning empty rather than a repr.", type(raw_template).__name__
    )
    return ""


def select_subject_template(copy_template: Any, business_id: Optional[str] = None) -> str:
    """Deterministically selects a subject line template for a lead.

    If copy_template['subject'] is a list (or copy_template['subjects'] is provided),
    picks one deterministically using a salted SHA256 hash of business_id.
    If copy_template['subject'] is a plain string, returns it directly for backward compatibility.
    """
    if isinstance(copy_template, dict):
        subject_raw = copy_template.get("subject")
        if subject_raw is None:
            subject_raw = copy_template.get("subjects", "")
    elif isinstance(copy_template, (list, str)):
        subject_raw = copy_template
    else:
        return ""

    return select_template_variant(subject_raw, business_id=business_id, salt="subject")


def select_body_template(
    copy_template: Any,
    business_id: Optional[str] = None,
    premise_verified: bool = True,
) -> str:
    """Deterministically selects a body template for a lead.

    Supports:
    1. Rich slot composition dictionary ({'middles': [...], 'closings': [...]})
    2. Flat list of whole body variants (['body1', 'body2'])
    3. Plain string body template

    When premise_verified is False and 'body_structure_unverified' is present in copy_template,
    picks from body_structure_unverified. Otherwise falls back to 'body_structure'.
    Uses independent SHA256 salting per slot ('body_middle', 'body_closing') so
    slot selections are mutually uncorrelated and uncorrelated with the subject.
    """
    if isinstance(copy_template, dict):
        body_raw = None
        if not premise_verified:
            body_raw = copy_template.get("body_structure_unverified")
        if body_raw is None:
            body_raw = copy_template.get("body_structure", "")
    elif isinstance(copy_template, (list, str)):
        body_raw = copy_template
    else:
        return ""

    return select_template_variant(body_raw, business_id=business_id, salt="body")


def select_followup_subject(
    copy_template: Any,
    step: int = 2,
    business_id: Optional[str] = None,
    first_subject: Optional[str] = None,
) -> str:
    """Deterministically selects a follow-up subject line template for a lead.

    Uses salted SHA256 hashing per business_id and per step.
    Supports '{first_subject}' token interpolation.
    """
    step_key = f"followup_step{step}"
    step_data = {}
    if isinstance(copy_template, dict):
        if step_key in copy_template:
            step_data = copy_template[step_key]
        elif "followups" in copy_template and str(step) in copy_template["followups"]:
            step_data = copy_template["followups"][str(step)]
        elif "followups" in copy_template and step in copy_template["followups"]:
            step_data = copy_template["followups"][step]
        elif "followup" in copy_template:
            step_data = copy_template["followup"]

    subject_raw = step_data.get("subject") if isinstance(step_data, dict) else None
    if not subject_raw:
        if first_subject:
            return f"re: {first_subject}"
        return select_subject_template(copy_template, business_id=business_id)

    raw = select_template_variant(subject_raw, business_id=business_id, salt=f"followup_step{step}_subject")
    if "{first_subject}" in raw:
        clean_first = first_subject or "quick question"
        raw = raw.replace("{first_subject}", clean_first)
    return raw


def select_followup_body(
    copy_template: Any,
    step: int = 2,
    business_id: Optional[str] = None,
    premise_verified: bool = True,
) -> str:
    """Deterministically selects a follow-up body template for a lead.

    When premise_verified is False and 'body_structure_unverified' is present in the step's copy,
    picks from body_structure_unverified. Otherwise falls back to 'body_structure'.
    """
    step_key = f"followup_step{step}"
    step_data = {}
    if isinstance(copy_template, dict):
        if step_key in copy_template:
            step_data = copy_template[step_key]
        elif "followups" in copy_template and str(step) in copy_template["followups"]:
            step_data = copy_template["followups"][str(step)]
        elif "followups" in copy_template and step in copy_template["followups"]:
            step_data = copy_template["followups"][step]
        elif "followup" in copy_template:
            step_data = copy_template["followup"]

    body_raw = None
    if isinstance(step_data, dict):
        if not premise_verified:
            body_raw = step_data.get("body_structure_unverified")
        if body_raw is None:
            body_raw = step_data.get("body_structure")

    if not body_raw:
        if step >= 3:
            body_raw = "if this is not a priority for {business_name} right now, no problem at all.\n\nshould i check back with you in a few months?"
        else:
            body_raw = "wanted to see if you had a moment to consider our note regarding {business_name}.\n\nwould you be open to a short 5-minute chat this week?"

    return select_template_variant(body_raw, business_id=business_id, salt=f"followup_step{step}_body")


class CampaignRouter:
    """Deterministic Campaign & Offer Router.

    Parses campaign_routing.yaml from the project root and evaluates
    lead metrics to assign the best campaign template and target offer.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        if config_path is None:
            config_path = BASE_DIR / "campaign_routing.yaml"
        self.config_path = config_path
        self.campaigns = self._load_config()

    def _load_config(self) -> List[Dict[str, Any]]:
        """Loads and parses campaign config file safely."""
        try:
            if not self.config_path.exists():
                logger.error(f"Campaign routing configuration file not found at: {self.config_path}")
                return []
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not data or "campaigns" not in data:
                    logger.warning("Campaign configuration file is empty or missing 'campaigns' key.")
                    return []
                return data.get("campaigns", [])
        except Exception as e:
            logger.error(f"Failed to load campaign routing config: {str(e)}")
            return []

    @staticmethod
    def select_subject(campaign_or_copy_template: Any, business_id: Optional[str] = None) -> str:
        """Helper to deterministically select a subject template for a campaign or copy_template."""
        if isinstance(campaign_or_copy_template, dict) and "copy_template" in campaign_or_copy_template:
            return select_subject_template(campaign_or_copy_template["copy_template"], business_id=business_id)
        return select_subject_template(campaign_or_copy_template, business_id=business_id)

    @staticmethod
    def select_body(
        campaign_or_copy_template: Any,
        business_id: Optional[str] = None,
        premise_verified: Optional[bool] = None,
    ) -> str:
        """Helper to deterministically select a body template for a campaign or copy_template."""
        if isinstance(campaign_or_copy_template, dict) and "copy_template" in campaign_or_copy_template:
            pv = premise_verified if premise_verified is not None else campaign_or_copy_template.get("premise_verified", True)
            return select_body_template(campaign_or_copy_template["copy_template"], business_id=business_id, premise_verified=pv)
        pv = premise_verified if premise_verified is not None else True
        return select_body_template(campaign_or_copy_template, business_id=business_id, premise_verified=pv)

    @staticmethod
    def select_followup_subject(
        campaign_or_copy_template: Any,
        step: int = 2,
        business_id: Optional[str] = None,
        first_subject: Optional[str] = None,
    ) -> str:
        """Helper to deterministically select a follow-up subject template for a campaign or copy_template."""
        if isinstance(campaign_or_copy_template, dict) and "copy_template" in campaign_or_copy_template:
            return select_followup_subject(campaign_or_copy_template["copy_template"], step=step, business_id=business_id, first_subject=first_subject)
        return select_followup_subject(campaign_or_copy_template, step=step, business_id=business_id, first_subject=first_subject)

    @staticmethod
    def select_followup_body(
        campaign_or_copy_template: Any,
        step: int = 2,
        business_id: Optional[str] = None,
        premise_verified: Optional[bool] = None,
    ) -> str:
        """Helper to deterministically select a follow-up body template for a campaign or copy_template."""
        if isinstance(campaign_or_copy_template, dict) and "copy_template" in campaign_or_copy_template:
            pv = premise_verified if premise_verified is not None else campaign_or_copy_template.get("premise_verified", True)
            return select_followup_body(campaign_or_copy_template["copy_template"], step=step, business_id=business_id, premise_verified=pv)
        pv = premise_verified if premise_verified is not None else True
        return select_followup_body(campaign_or_copy_template, step=step, business_id=business_id, premise_verified=pv)

    @staticmethod
    def render_subject(template: str, business_name: Optional[str] = None, max_chars: int = 50, **kwargs) -> str:
        """Renders subject template with cleaned business name and grounded topic,
        guaranteeing the result never exceeds max_chars through a progressive fallback cascade.
        """
        from leadforge.outreach.generator import compress_specific_topic

        raw_biz = business_name or kwargs.get("business_name") or kwargs.get("business_name_full") or ""
        clean_name = clean_company_name(raw_biz)
        topic_raw = kwargs.get("specific_topic") or kwargs.get("topic_focus") or kwargs.get("category") or "manufacturing"
        topic = compress_specific_topic(str(topic_raw), max_words=3)
        if not topic:
            topic = "manufacturing"

        # 1. Standard template interpolation with clean business name
        vars_map = {
            "business_name": clean_name,
            "topic_focus": topic,
            "specific_topic": topic,
            **kwargs,
        }
        out = template
        for k, v in vars_map.items():
            out = out.replace(f"{{{k}}}", str(v))
        out = re.sub(r"\s+", " ", out).strip()

        if len(out) <= max_chars:
            return out

        # 2. Drop opening prefix if present
        opening_prefix_pattern = r"^(quick note:|question:|note on|idea for|re:|quick thought:|inquiry re:|details:|brief note:|regarding|checking in:|quick question:|a thought on|an idea for|overview of|details on|a note regarding|quick question on|brief thought on)\s*"
        stripped_opening = re.sub(opening_prefix_pattern, "", out, flags=re.IGNORECASE).strip()
        if stripped_opening and len(stripped_opening) <= max_chars:
            return stripped_opening

        # 3. Use shortened business name with opening
        short_name = shorten_company_name(clean_name, max_chars=18)
        vars_map_short = {**vars_map, "business_name": short_name}
        out_short = template
        for k, v in vars_map_short.items():
            out_short = out_short.replace(f"{{{k}}}", str(v))
        out_short = re.sub(r"\s+", " ", out_short).strip()
        if len(out_short) <= max_chars:
            return out_short

        # 4. Use shortened business name without opening
        stripped_short = re.sub(opening_prefix_pattern, "", out_short, flags=re.IGNORECASE).strip()
        if stripped_short and len(stripped_short) <= max_chars:
            return stripped_short

        # 5. Minimal grounded fallback: "{topic} - {short_name}"
        minimal = f"{topic} - {short_name}".strip()
        if len(minimal) <= max_chars:
            return minimal

        # 6. Hard guarantee: Word boundary truncation up to max_chars
        words = minimal.split()
        res = []
        curr = 0
        for w in words:
            add = len(w) if not res else len(w) + 1
            if curr + add <= max_chars:
                res.append(w)
                curr += add
            else:
                break
        if res:
            return " ".join(res).strip(".,-& :")
        return minimal[:max_chars].strip()

    @staticmethod
    def render_body(template: str, business_name: str, **kwargs) -> str:
        """Renders body template with cleaned business name, resolving slot tokens
        and defensively preventing opening sentence location collisions.
        """
        clean_name = clean_company_name(business_name)
        vars_map = {"business_name": clean_name, **kwargs}

        if "{contact_bridge}" in template and "contact_bridge" not in vars_map:
            from leadforge.outreach.generator import generate_contact_bridge
            hook = kwargs.get("observation_hook", "")
            city = kwargs.get("city", "")
            specific_topic = kwargs.get("specific_topic") or kwargs.get("topic_focus", "")
            scraped_text = kwargs.get("scraped_text", "")
            raw_name = kwargs.get("business_name_full", business_name)
            biz_id = kwargs.get("business_id")
            category = kwargs.get("category", "")
            bridge, _ = generate_contact_bridge(
                business_name=clean_name,
                raw_name=raw_name,
                city=city,
                hook=hook,
                specific_topic=specific_topic,
                scraped_text=scraped_text,
                business_id=biz_id,
                category=category,
            )
            vars_map["contact_bridge"] = bridge

        out = template
        for k, v in vars_map.items():
            out = out.replace(f"{{{k}}}", str(v))
        out = re.sub(r"\{[a-zA-Z0-9_]+\}", "", out)

        city = kwargs.get("city")
        if city and str(city).strip():
            c_clean = str(city).strip()
            paras = [p.strip() for p in out.split("\n\n") if p.strip()]
            if len(paras) >= 2:
                p1 = paras[0]
                p2 = paras[1]
                city_pat = re.compile(rf"\b{re.escape(c_clean)}\b", re.IGNORECASE)
                if city_pat.search(p1) and city_pat.search(p2):
                    p2_fixed = re.sub(
                        rf"\b(?:based\s+here\s+in|based\s+in|here\s+in|in)\s+{re.escape(c_clean)}\b",
                        "locally",
                        p2,
                        flags=re.IGNORECASE,
                    )
                    if p2_fixed == p2:
                        p2_fixed = re.sub(
                            rf"\b{re.escape(c_clean)}\b",
                            "local",
                            p2,
                            flags=re.IGNORECASE,
                        )
                    paras[1] = p2_fixed
                    out = "\n\n".join(paras)

        return out.strip()

    def route_lead(
        self,
        category: str,
        has_website: bool,
        ssl_valid: bool = True,
        load_time_seconds: float = 0.0,
        has_booking: Optional[bool] = None,
        has_order_flow: Optional[bool] = None,
        has_contact_form: Optional[bool] = None,
        audit_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Evaluates routing criteria against lead properties.

        Returns:
            Matched campaign dictionary containing name, target_offer, and copy_template
            or None if no campaign criteria are satisfied.
        """
        category_clean = (category or "").strip().lower()

        if audit_data:
            if has_booking is None:
                has_booking = audit_data.get("has_booking")
            if has_order_flow is None:
                has_order_flow = audit_data.get("has_order_flow")
                if has_order_flow is None and audit_data.get("cms") in (
                    "Shopify", "WooCommerce", "Magento", "BigCommerce", "PrestaShop", "OpenCart"
                ):
                    has_order_flow = True
            if has_contact_form is None:
                has_contact_form = audit_data.get("has_contact_form")

        for campaign in self.campaigns:
            criteria = campaign.get("criteria", {})

            # 1. Check website presence criteria
            req_has_website = criteria.get("has_website")
            if req_has_website is not None and req_has_website != has_website:
                continue

            # 2. Check SSL validation criteria
            req_ssl_valid = criteria.get("ssl_valid")
            if req_ssl_valid is not None and req_ssl_valid != ssl_valid:
                continue

            # 3. Check load time criteria
            max_load_time = criteria.get("max_load_time_seconds")
            if max_load_time is not None and load_time_seconds > max_load_time:
                continue

            # 4-6. Premise gating.
            # A campaign whose copy asserts the absence of a capability
            # (`has_booking: false`) must never be sent to a business that
            # demonstrably HAS it. Missing evidence is *unknown*, not absence:
            # unknown still routes here, but the campaign is flagged so the
            # composer does not assert the claim as fact.
            premise_unverified = []
            premise_conflict = False
            for crit_key, evidence in (
                ("has_booking", has_booking),
                ("has_order_flow", has_order_flow),
                ("has_contact_form", has_contact_form),
            ):
                required = criteria.get(crit_key)
                if required is None:
                    continue
                if required is False:
                    # Only positive evidence disqualifies.
                    if evidence is True:
                        premise_conflict = True
                        break
                    if evidence is None:
                        premise_unverified.append(crit_key)
                else:  # required is True
                    if evidence is not True:
                        premise_conflict = True
                        break
            if premise_conflict:
                continue

            # 7. Check category list criteria
            req_categories = criteria.get("categories")
            if req_categories is not None:
                if not category_clean:
                    # Unknown category can never satisfy a category-restricted campaign.
                    continue
                allowed_cats = [str(c).strip().lower() for c in req_categories]
                matched_cat = False
                for c in allowed_cats:
                    c_stem = c.rstrip("s")
                    cat_stem = category_clean.rstrip("s")
                    if (
                        c == category_clean
                        or c in category_clean
                        or category_clean in c
                        or (len(c_stem) >= 3 and c_stem in category_clean)
                        or (len(cat_stem) >= 3 and cat_stem in c)
                    ):
                        matched_cat = True
                        break
                if not matched_cat:
                    continue

            # All conditions met, return matched campaign config.
            # Shallow-copy so per-lead premise metadata never mutates the
            # shared loaded config.
            matched = dict(campaign)
            matched["premise_verified"] = not premise_unverified
            matched["premise_unverified_fields"] = list(premise_unverified)
            return matched

        return None
