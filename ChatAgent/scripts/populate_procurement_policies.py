"""
Populates the BigQuery `procurement_policies` table with curated, verified procurement
policies grounded in real UK and international sustainability frameworks.

The primary source is the CURATED_POLICIES dict below — every policy is traceable to a
real standard, regulation, or certification body. LLM supplementation is opt-in via
--supplement-with-llm and only adds policies not already present by name.

Usage:
    python populate_procurement_policies.py [--industries "Retail,Manufacturing"] [--dry-run]
    python populate_procurement_policies.py --supplement-with-llm

Run once per industry (or re-run to refresh). Idempotent: upserts by (industry, policy_name).
"""

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone

import dotenv
import requests
from google import genai
from google.cloud import bigquery
from google.genai.types import GenerateContentConfig

dotenv.load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID", "dash-beta-e61d0")
DATASET_ID = "dash_beta_database"
TABLE_ID = "procurement_policies"
GEMINI_MODEL = "gemini-2.5-pro"
GOOGLE_SEARCH_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_SEARCH_CX = os.getenv("GOOGLE_CSE_ID")

POLICY_SCHEMA = [
    bigquery.SchemaField("policy_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("industry", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("policy_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("policy_source", "STRING"),
    bigquery.SchemaField("policy_description", "STRING"),
    bigquery.SchemaField("category", "STRING"),
    bigquery.SchemaField("last_updated", "TIMESTAMP"),
]

# ---------------------------------------------------------------------------
# Cross-industry universal policies — added to every industry
# ---------------------------------------------------------------------------
UNIVERSAL_POLICIES = [
    {
        "policy_name": "PPN 06/21 Carbon Reduction Plan",
        "policy_description": (
            "UK government mandatory requirement for suppliers bidding on public contracts "
            "above £5M to publish a Carbon Reduction Plan declaring Scope 1, 2, and material "
            "Scope 3 emissions, with a commitment to achieve net zero by 2050."
        ),
        "category": "environmental",
        "policy_source": "UK Cabinet Office Procurement Policy Note 06/21",
    },
    {
        "policy_name": "Modern Slavery Act 2015 Transparency Statement",
        "policy_description": (
            "UK legislative requirement for organisations with annual turnover above £36M to "
            "publish an annual statement detailing steps taken to prevent slavery and human "
            "trafficking across their operations and supply chains."
        ),
        "category": "social",
        "policy_source": "UK Modern Slavery Act 2015",
    },
    {
        "policy_name": "SECR Streamlined Energy and Carbon Reporting",
        "policy_description": (
            "UK mandatory annual reporting requirement for quoted companies, large unquoted "
            "companies, and large LLPs to disclose energy use, Scope 1 and 2 carbon emissions, "
            "and at least one energy efficiency improvement measure."
        ),
        "category": "reporting",
        "policy_source": "UK Companies Act 2006 (as amended), DESNZ SECR Guidance",
    },
    {
        "policy_name": "TCFD Climate-Related Financial Disclosures",
        "policy_description": (
            "Framework — mandatory for UK premium-listed companies and large asset managers — "
            "requiring disclosure of governance, strategy, risk management, and metrics related "
            "to climate-related risks and opportunities."
        ),
        "category": "reporting",
        "policy_source": "Task Force on Climate-related Financial Disclosures (TCFD); FCA PS21/23",
    },
    {
        "policy_name": "Science Based Targets (SBTi) Emissions Reduction Commitment",
        "policy_description": (
            "Requirement to set independently validated Scope 1, 2, and 3 emissions reduction "
            "targets aligned with a 1.5°C pathway through the Science Based Targets initiative, "
            "with interim milestones and annual progress disclosure."
        ),
        "category": "environmental",
        "policy_source": "Science Based Targets initiative (SBTi)",
    },
    {
        "policy_name": "ISO 14001:2015 Environmental Management System",
        "policy_description": (
            "International standard requiring a certified environmental management system "
            "covering environmental aspects, legal compliance obligations, and a programme of "
            "continual improvement to reduce environmental footprint."
        ),
        "category": "certification",
        "policy_source": "ISO 14001:2015 (International Organization for Standardization)",
    },
    {
        "policy_name": "GRI Standards Sustainability Reporting",
        "policy_description": (
            "Widely adopted framework for comprehensive sustainability disclosure across "
            "economic, environmental, and social topics (GRI 200/300/400 series); increasingly "
            "required by institutional buyers as evidence of transparency and accountability."
        ),
        "category": "reporting",
        "policy_source": "Global Reporting Initiative (GRI Standards 2021)",
    },
]

# ---------------------------------------------------------------------------
# Industry-specific curated policies
# Each entry is traceable to a named real standard, regulation, or body.
# ---------------------------------------------------------------------------
CURATED_POLICIES = {

    "Retail": [
        {
            "policy_name": "Ethical Trading Initiative (ETI) Base Code Compliance",
            "policy_description": (
                "Requirement for suppliers to meet the ETI Base Code covering fair wages, "
                "working hours, freedom of association, child and forced labour prevention, "
                "and safe working conditions — audited through SMETA or equivalent."
            ),
            "category": "social",
            "policy_source": "Ethical Trading Initiative (ETI Base Code)",
        },
        {
            "policy_name": "Sedex SMETA Supply Chain Audit",
            "policy_description": (
                "Third-party supplier audit via the Sedex Members Ethical Trade Audit (SMETA) "
                "covering labour practices, health and safety, environment, and business ethics "
                "at manufacturing and processing sites."
            ),
            "category": "supply_chain",
            "policy_source": "Sedex (Supplier Ethical Data Exchange)",
        },
        {
            "policy_name": "UK Plastic Packaging Tax Compliance and Recycled Content",
            "policy_description": (
                "UK legal requirement that plastic packaging placed on the market contains at "
                "least 30% recycled content; suppliers must provide recycled content "
                "declarations and comply with HMRC reporting obligations."
            ),
            "category": "environmental",
            "policy_source": "UK Plastic Packaging Tax (Finance Act 2021, effective April 2022)",
        },
        {
            "policy_name": "FSC / PEFC Certification for Timber and Paper Packaging",
            "policy_description": (
                "Procurement requirement that all paper, cardboard, and timber-based packaging "
                "or products carry FSC or PEFC certification, demonstrating responsible forest "
                "management and verified chain of custody."
            ),
            "category": "certification",
            "policy_source": "Forest Stewardship Council (FSC); Programme for the Endorsement of Forest Certification (PEFC)",
        },
        {
            "policy_name": "Rainforest Alliance / UTZ Certification for Key Commodities",
            "policy_description": (
                "Certification requirement for sourcing coffee, cocoa, tea, and bananas from "
                "Rainforest Alliance certified farms demonstrating environmental conservation, "
                "social responsibility, and supply chain traceability."
            ),
            "category": "certification",
            "policy_source": "Rainforest Alliance (merged with UTZ Certification, 2018)",
        },
        {
            "policy_name": "Living Wage Foundation Accreditation",
            "policy_description": (
                "Procurement requirement that suppliers pay, or are actively transitioning to, "
                "the independently calculated UK Living Wage (and London Living Wage where "
                "applicable) for all directly employed staff."
            ),
            "category": "social",
            "policy_source": "Living Wage Foundation (UK)",
        },
        {
            "policy_name": "Fair Trade Certification",
            "policy_description": (
                "Supplier certification requirement for commodity sourcing (coffee, cocoa, "
                "cotton, sugar) from Fairtrade-certified producers, ensuring a minimum price, "
                "Fairtrade Premium, and safe working conditions."
            ),
            "category": "certification",
            "policy_source": "Fairtrade Foundation (UK); Fairtrade International",
        },
        {
            "policy_name": "RSPCA Assured Animal Welfare Certification",
            "policy_description": (
                "For food retail: requirement that animal products (meat, eggs, dairy, fish) "
                "are sourced from RSPCA Assured certified farms meeting higher animal welfare "
                "standards across all stages of production."
            ),
            "category": "certification",
            "policy_source": "RSPCA Assured (Royal Society for the Prevention of Cruelty to Animals)",
        },
        {
            "policy_name": "Single-Use Plastics Reduction Commitment (WRAP)",
            "policy_description": (
                "Supplier commitment to phase out avoidable single-use plastics from product "
                "packaging by agreed milestones, aligned with WRAP's UK Plastics Pact targets "
                "and the UK Government's Single-Use Plastics regulations."
            ),
            "category": "environmental",
            "policy_source": "WRAP UK Plastics Pact; UK Single-Use Plastics Regulations 2023",
        },
        {
            "policy_name": "Conflict Minerals Responsible Sourcing (3TG Due Diligence)",
            "policy_description": (
                "Supplier requirement to conduct due diligence on sourcing of tin, tantalum, "
                "tungsten, and gold (3TG); publish annual conflict minerals declarations; and "
                "work through the Responsible Minerals Initiative (RMI) smelter programme."
            ),
            "category": "supply_chain",
            "policy_source": "Responsible Minerals Initiative (RMI); OECD Due Diligence Guidance for Responsible Mineral Supply Chains",
        },
        {
            "policy_name": "B Corp Certification",
            "policy_description": (
                "Voluntary certification requiring verified high standards of social and "
                "environmental performance, public transparency, and legal accountability; "
                "increasingly required by ethical retail brands for strategic suppliers."
            ),
            "category": "certification",
            "policy_source": "B Lab (B Corp Certification)",
        },
    ],

    "Manufacturing": [
        {
            "policy_name": "ISO 45001:2018 Occupational Health and Safety Management",
            "policy_description": (
                "International standard requiring a certified OH&S management system covering "
                "hazard identification, risk controls, worker participation, incident investigation, "
                "and continual improvement to eliminate work-related injury and ill health."
            ),
            "category": "certification",
            "policy_source": "ISO 45001:2018 (International Organization for Standardization)",
        },
        {
            "policy_name": "ISO 50001:2018 Energy Management System",
            "policy_description": (
                "International standard requiring systematic monitoring, measurement, and "
                "reduction of energy consumption; suppliers must set energy performance "
                "baselines, implement improvement plans, and achieve ISO 50001 certification."
            ),
            "category": "certification",
            "policy_source": "ISO 50001:2018 (International Organization for Standardization)",
        },
        {
            "policy_name": "ESOS Energy Savings Opportunity Scheme",
            "policy_description": (
                "UK mandatory scheme requiring large organisations (250+ employees or £44M+ "
                "turnover) to conduct an ESOS energy audit every four years, identify energy "
                "saving opportunities, and notify the Environment Agency of compliance."
            ),
            "category": "environmental",
            "policy_source": "UK Energy Savings Opportunity Scheme (ESOS) Regulations 2014",
        },
        {
            "policy_name": "UK Emissions Trading Scheme (UK ETS) Compliance",
            "policy_description": (
                "Regulatory requirement for installations in energy-intensive industries to "
                "monitor and report greenhouse gas emissions, surrender sufficient UK ETS "
                "allowances annually, and comply with the UK ETS Authority's rules."
            ),
            "category": "environmental",
            "policy_source": "UK Emissions Trading Scheme; UK ETS Authority (DESNZ, Ofgem, EA, SEPA, NRW)",
        },
        {
            "policy_name": "ZDHC Manufacturing Restricted Substances List (MRSL) Compliance",
            "policy_description": (
                "Requirement to eliminate hazardous chemicals from manufacturing processes per "
                "the Zero Discharge of Hazardous Chemicals (ZDHC) MRSL; verified through "
                "ZDHC-approved laboratory testing and supplier conformance reporting."
            ),
            "category": "environmental",
            "policy_source": "ZDHC Foundation — MRSL v3.1",
        },
        {
            "policy_name": "Responsible Minerals Initiative (RMI) Conflict Minerals Programme",
            "policy_description": (
                "Supplier due diligence requirement on sourcing of 3TG minerals (tin, tantalum, "
                "tungsten, gold) and cobalt; participation in the RMI Responsible Minerals "
                "Assurance Process (RMAP) for smelter/refiner verification."
            ),
            "category": "supply_chain",
            "policy_source": "Responsible Minerals Initiative (RMI); OECD Due Diligence Guidance",
        },
        {
            "policy_name": "Extended Producer Responsibility for Packaging Waste",
            "policy_description": (
                "UK obligation for producers, importers, and sellers of packaging to register, "
                "report packaging data, fund recycling infrastructure, and meet material-specific "
                "recycling targets under the new EPR for Packaging regulations."
            ),
            "category": "environmental",
            "policy_source": "UK Extended Producer Responsibility for Packaging (EPR) Regulations 2024",
        },
        {
            "policy_name": "EMAS EU Eco-Management and Audit Scheme",
            "policy_description": (
                "Voluntary but increasingly required environmental management standard allowing "
                "organisations to register after conducting an environmental review, establishing "
                "an environmental management system, and publishing a verified environmental statement."
            ),
            "category": "certification",
            "policy_source": "European Commission EMAS Regulation (EC) No 1221/2009",
        },
        {
            "policy_name": "Supply Chain Tier Mapping and Transparency",
            "policy_description": (
                "Procurement requirement for suppliers to map their own supply chains to at "
                "least Tier 2, identify sustainability and human rights risks at each tier, "
                "and implement monitoring or audit programmes for critical suppliers."
            ),
            "category": "supply_chain",
            "policy_source": "OECD Guidelines for Multinational Enterprises; UN Guiding Principles on Business and Human Rights",
        },
        {
            "policy_name": "PAS 2060 Carbon Neutrality Verification",
            "policy_description": (
                "BSI standard for demonstrating and verifying a claim of carbon neutrality, "
                "requiring a carbon footprint assessment, a carbon management plan with "
                "reduction targets, and verified offsetting of remaining emissions."
            ),
            "category": "certification",
            "policy_source": "BSI PAS 2060:2014 (British Standards Institution)",
        },
        {
            "policy_name": "ISO 14046 Water Footprint Assessment",
            "policy_description": (
                "Standard for quantifying and reporting the water footprint of products, "
                "processes, and organisations; suppliers in water-intensive sectors required to "
                "measure consumption and discharge, set reduction targets, and report annually."
            ),
            "category": "environmental",
            "policy_source": "ISO 14046:2014 (International Organization for Standardization)",
        },
    ],

    "Construction": [
        {
            "policy_name": "BREEAM Building Research Establishment Assessment Method",
            "policy_description": (
                "UK's leading sustainability assessment method for buildings; procurement "
                "requirement for new construction and major refurbishment projects to target "
                "a minimum BREEAM rating (typically 'Very Good' or 'Excellent') across "
                "categories including energy, materials, waste, and ecology."
            ),
            "category": "certification",
            "policy_source": "Building Research Establishment (BRE) — BREEAM",
        },
        {
            "policy_name": "PAS 2080 Carbon Management in Infrastructure",
            "policy_description": (
                "BSI standard for managing and reducing whole-life carbon in infrastructure "
                "projects; suppliers must establish carbon targets, measure embodied and "
                "operational carbon, and report progress against a carbon reduction hierarchy."
            ),
            "category": "environmental",
            "policy_source": "BSI PAS 2080:2023 (British Standards Institution)",
        },
        {
            "policy_name": "CDM 2015 Health and Safety Compliance",
            "policy_description": (
                "UK legal requirement under the Construction (Design and Management) Regulations "
                "2015; all duty holders must fulfil designated CDM roles, maintain a health and "
                "safety file, and pre-construction information must be compiled and shared."
            ),
            "category": "social",
            "policy_source": "UK Construction (Design and Management) Regulations 2015 (CDM 2015), HSE",
        },
        {
            "policy_name": "FSC / PEFC Certified Timber and Wood Products",
            "policy_description": (
                "Procurement requirement that all structural timber, formwork, hoarding, and "
                "wood-based products carry FSC or PEFC certification confirming responsible "
                "forest management and legal harvesting."
            ),
            "category": "certification",
            "policy_source": "Forest Stewardship Council (FSC); PEFC International",
        },
        {
            "policy_name": "Construction Waste Management and Landfill Diversion",
            "policy_description": (
                "Supplier commitment to implement a Site Waste Management Plan achieving at "
                "least 90% diversion of construction and demolition waste from landfill, with "
                "segregated waste streams and verified recycling/recovery records."
            ),
            "category": "environmental",
            "policy_source": "WRAP Net Waste Tool; UK Site Waste Management Plans (Environmental Protection Regulations)",
        },
        {
            "policy_name": "Whole Life Carbon Assessment (EN 15978 / RICS Guidance)",
            "policy_description": (
                "Requirement for suppliers to conduct a whole life carbon assessment per EN 15978 "
                "covering embodied carbon (A1–A5, C, D stages) and operational carbon, informed "
                "by Environmental Product Declarations (EPDs) for specified materials."
            ),
            "category": "reporting",
            "policy_source": "BS EN 15978:2011; RICS Whole Life Carbon Assessment Professional Statement (1st ed.)",
        },
        {
            "policy_name": "BIM Level 2 / ISO 19650 Information Management",
            "policy_description": (
                "Mandatory for UK government-funded projects: suppliers must deliver project "
                "information per BIM Level 2 / ISO 19650 standards, including asset data and "
                "environmental product information (including embodied carbon) in common data environments."
            ),
            "category": "governance",
            "policy_source": "UK Government BIM Mandate (2016); ISO 19650-1/2:2018",
        },
        {
            "policy_name": "Low Emission Zone and ULEZ Vehicle Compliance",
            "policy_description": (
                "For sites in Greater London and other Clean Air Zones: all site vehicles and "
                "Non-Road Mobile Machinery (NRMM) must meet minimum emission standards (Euro VI "
                "for HGVs, Stage V for NRMM) and comply with the Mayor of London's NRMM register."
            ),
            "category": "environmental",
            "policy_source": "Greater London Authority NRMM Low Emission Zone; UK Clean Air Zones Framework",
        },
        {
            "policy_name": "Social Value Act 2012 Commitments",
            "policy_description": (
                "Requirement for public sector construction suppliers to demonstrate social value "
                "beyond contract deliverables — covering local employment, skills training, supply "
                "chain diversity, and community benefits — reported against agreed metrics."
            ),
            "category": "social",
            "policy_source": "Public Services (Social Value) Act 2012; Cabinet Office Social Value Model",
        },
        {
            "policy_name": "Considerate Constructors Scheme (CCS) Registration",
            "policy_description": (
                "Voluntary but widely required industry scheme: registered sites are independently "
                "monitored against the Code of Considerate Practice covering care for the "
                "environment, community, and workforce."
            ),
            "category": "social",
            "policy_source": "Considerate Constructors Scheme (CCS)",
        },
    ],

    "Financial Services": [
        {
            "policy_name": "FCA Consumer Duty — Good Consumer Outcomes",
            "policy_description": (
                "FCA regulatory requirement for firms to deliver good outcomes for retail "
                "customers across four areas: products and services, price and value, consumer "
                "understanding, and consumer support; with Board attestation of compliance."
            ),
            "category": "governance",
            "policy_source": "FCA Consumer Duty (PS22/9, effective July 2023)",
        },
        {
            "policy_name": "SFDR Sustainable Finance Disclosure Regulation",
            "policy_description": (
                "EU/UK-aligned requirement for financial market participants to disclose how "
                "sustainability risks are integrated into investment decisions, publish entity-level "
                "Principal Adverse Impact (PAI) statements, and classify products under Articles 6/8/9."
            ),
            "category": "reporting",
            "policy_source": "EU SFDR (Regulation (EU) 2019/2088); UK equivalent FCA ESG rules",
        },
        {
            "policy_name": "Net Zero Banking Alliance / Net Zero Asset Managers Commitment",
            "policy_description": (
                "Commitment to align lending and investment portfolios with net-zero emissions "
                "by 2050, set interim targets for 2030, and publish annual transition plans — "
                "verified against NZBA or NZAM framework guidelines."
            ),
            "category": "environmental",
            "policy_source": "UN-convened Net Zero Banking Alliance (NZBA); Net Zero Asset Managers Initiative (NZAM)",
        },
        {
            "policy_name": "UK Stewardship Code 2020",
            "policy_description": (
                "FRC requirement for asset managers and asset owners to demonstrate purposeful "
                "stewardship — engaging investee companies on ESG issues, exercising voting "
                "rights, and reporting against all 12 Principles with evidence of outcomes."
            ),
            "category": "governance",
            "policy_source": "Financial Reporting Council (FRC) UK Stewardship Code 2020",
        },
        {
            "policy_name": "UN Principles for Responsible Investment (UNPRI)",
            "policy_description": (
                "Voluntary commitment framework for investors to incorporate ESG factors into "
                "investment analysis and decision-making, engage on ESG issues, seek disclosure "
                "from investees, and report annually against UNPRI reporting framework."
            ),
            "category": "governance",
            "policy_source": "UN-supported Principles for Responsible Investment (UNPRI)",
        },
        {
            "policy_name": "AML / KYC Compliance and Financial Crime Controls",
            "policy_description": (
                "FCA regulatory obligation to implement Customer Due Diligence (CDD), Enhanced "
                "Due Diligence (EDD) for high-risk clients, transaction monitoring, and Suspicious "
                "Activity Reporting (SAR) under the Money Laundering Regulations 2017."
            ),
            "category": "governance",
            "policy_source": "UK Money Laundering, Terrorist Financing and Transfer of Funds Regulations 2017; FCA Financial Crime Guide",
        },
        {
            "policy_name": "ISO 27001 Information Security Management",
            "policy_description": (
                "International standard for information security management systems; financial "
                "services suppliers increasingly required to hold ISO 27001 certification "
                "demonstrating systematic management of information security risks and controls."
            ),
            "category": "certification",
            "policy_source": "ISO/IEC 27001:2022 (International Organization for Standardization)",
        },
        {
            "policy_name": "Gender Pay Gap Reporting (Equality Act 2010)",
            "policy_description": (
                "UK legal requirement for employers with 250+ employees to publish annual gender "
                "pay gap data (mean and median pay, bonus gaps, pay quartiles) on the government "
                "portal and company website, with an accompanying narrative and action plan."
            ),
            "category": "social",
            "policy_source": "Equality Act 2010 (Gender Pay Gap Information) Regulations 2017",
        },
        {
            "policy_name": "Climate Transition Plan Publication (FCA TP Taskforce)",
            "policy_description": (
                "Requirement for UK-listed companies and large financial institutions to publish "
                "a credible climate transition plan covering governance, strategy, targets, and "
                "actions aligned with the UK Transition Plan Taskforce (TPT) disclosure framework."
            ),
            "category": "reporting",
            "policy_source": "UK Transition Plan Taskforce (TPT) Disclosure Framework (2023); FCA Listing Rules",
        },
        {
            "policy_name": "UK Green Taxonomy / EU Taxonomy Alignment Reporting",
            "policy_description": (
                "Requirement for qualifying financial products to disclose the proportion of "
                "investments aligned with the EU Taxonomy environmental objectives (climate "
                "mitigation, adaptation, water, circular economy, pollution, biodiversity)."
            ),
            "category": "reporting",
            "policy_source": "EU Taxonomy Regulation (EU) 2020/852; UK Green Taxonomy (in development)",
        },
        {
            "policy_name": "UNPRI Stewardship and Engagement on Climate Risk",
            "policy_description": (
                "Investor requirement to engage portfolio companies on climate risk management, "
                "vote against directors where climate governance is inadequate, and collaborate "
                "on systemic climate risk through investor coalitions (CA100+, IIGCC)."
            ),
            "category": "governance",
            "policy_source": "Climate Action 100+ (CA100+); Institutional Investors Group on Climate Change (IIGCC)",
        },
    ],

    "Healthcare": [
        {
            "policy_name": "NHS Net Zero Supplier Roadmap (Greener NHS)",
            "policy_description": (
                "NHS England requirement that suppliers to the NHS demonstrate a Carbon Reduction "
                "Plan aligned with NHS net-zero targets (operations net zero by 2040, supply chain "
                "net zero by 2045), with Scope 1, 2, and 3 emissions disclosure."
            ),
            "category": "environmental",
            "policy_source": "NHS England Greener NHS Programme; NHS Net Zero Supplier Roadmap (2022)",
        },
        {
            "policy_name": "MHRA Medicines and Medical Devices Regulatory Compliance",
            "policy_description": (
                "UK legal requirement for all medicines and medical devices to obtain MHRA "
                "approval; manufacturers must maintain a Quality Management System (ISO 13485 "
                "for devices), conduct post-market surveillance, and report adverse events."
            ),
            "category": "certification",
            "policy_source": "UK Medicines and Healthcare products Regulatory Agency (MHRA)",
        },
        {
            "policy_name": "NHS Data Security and Protection Toolkit (DSPT)",
            "policy_description": (
                "Annual self-assessment requirement for organisations handling NHS patient data "
                "to demonstrate compliance with the National Data Guardian's ten data security "
                "standards, verified against the NHS DSPT framework."
            ),
            "category": "governance",
            "policy_source": "NHS Digital Data Security and Protection Toolkit (DSPT)",
        },
        {
            "policy_name": "Good Manufacturing Practice (GMP) and ISO 13485",
            "policy_description": (
                "Regulatory requirement for pharmaceutical and medical device manufacturers to "
                "comply with GMP standards and hold ISO 13485 certification, demonstrating "
                "consistent quality management, traceability, and validated manufacturing processes."
            ),
            "category": "certification",
            "policy_source": "EMA/MHRA Good Manufacturing Practice Guidelines; ISO 13485:2016",
        },
        {
            "policy_name": "Clinical Waste Management Compliance (Special Waste Regulations)",
            "policy_description": (
                "Legal requirement for healthcare suppliers to segregate, treat, and safely "
                "dispose of clinical, pharmaceutical, and hazardous waste in accordance with "
                "the UK Hazardous Waste Regulations, with duty of care documentation."
            ),
            "category": "environmental",
            "policy_source": "UK Hazardous Waste (England and Wales) Regulations 2005; HSE Health and Social Care Sector Guidance",
        },
        {
            "policy_name": "Antimicrobial Resistance (AMR) Stewardship Commitment",
            "policy_description": (
                "Pharmaceutical and agri-food supplier commitment to support the UK's National "
                "Action Plan on AMR: restricting antibiotic sales/use, adopting responsible "
                "prescribing guidelines, and publishing antibiotic usage data annually."
            ),
            "category": "social",
            "policy_source": "UK 5-year National Action Plan on AMR 2024–2029; WHO AMR Global Action Plan",
        },
        {
            "policy_name": "NHS Social Value Framework Compliance",
            "policy_description": (
                "Requirement for NHS suppliers to deliver measurable social value against the "
                "NHS Social Value Framework's five themes: COVID-19 recovery, tackling economic "
                "inequality, fighting climate change, equal opportunity, and wellbeing."
            ),
            "category": "social",
            "policy_source": "NHS England Social Value Framework (2020)",
        },
        {
            "policy_name": "Single-Use Plastics Reduction in Healthcare (NHS SOP)",
            "policy_description": (
                "NHS procurement requirement to phase out avoidable single-use plastics in "
                "non-clinical applications (catering, admin, packaging); suppliers must provide "
                "alternatives and report on plastic reduction progress annually."
            ),
            "category": "environmental",
            "policy_source": "NHS Greener NHS Sustainable Procurement Strategy; WRAP NHS",
        },
        {
            "policy_name": "Care Quality Commission (CQC) Fundamental Standards",
            "policy_description": (
                "UK regulatory requirement for registered health and social care providers to "
                "meet the CQC Fundamental Standards covering person-centred care, safety, "
                "safeguarding, staffing, premises, and governance; subject to inspection."
            ),
            "category": "governance",
            "policy_source": "Care Quality Commission (CQC) — Health and Social Care Act 2008 (Regulated Activities) Regulations 2014",
        },
        {
            "policy_name": "ISO 45001 Occupational Health and Safety (Healthcare Settings)",
            "policy_description": (
                "Certification requirement for healthcare suppliers demonstrating systematic "
                "management of occupational health and safety risks, including clinical hazards, "
                "manual handling, infection risk, and worker mental health."
            ),
            "category": "certification",
            "policy_source": "ISO 45001:2018 (International Organization for Standardization)",
        },
    ],

    "Technology": [
        {
            "policy_name": "WEEE Directive — Extended Producer Responsibility",
            "policy_description": (
                "UK legal requirement for producers, distributors, and retailers of electrical "
                "and electronic equipment to register, fund collection and recycling of WEEE, "
                "meet material recovery targets, and label products with the crossed-out bin symbol."
            ),
            "category": "environmental",
            "policy_source": "UK Waste Electrical and Electronic Equipment Regulations 2013 (implementing EU WEEE Directive)",
        },
        {
            "policy_name": "EU Ecodesign Regulation and Energy Labelling",
            "policy_description": (
                "Requirement for electronic and energy-related products to meet minimum energy "
                "efficiency standards under UK/EU Ecodesign regulations and carry accurate energy "
                "labels; suppliers must provide product environmental data sheets."
            ),
            "category": "environmental",
            "policy_source": "EU Ecodesign Directive 2009/125/EC; UK Ecodesign for Energy-Related Products Regulations 2021",
        },
        {
            "policy_name": "ISO 27001 Information Security Management System",
            "policy_description": (
                "International standard for information security management; technology suppliers "
                "increasingly required by enterprise and public sector buyers to hold ISO 27001 "
                "certification demonstrating systematic management of cyber security risks."
            ),
            "category": "certification",
            "policy_source": "ISO/IEC 27001:2022 (International Organization for Standardization)",
        },
        {
            "policy_name": "Right to Repair — EU / UK Product Longevity Requirements",
            "policy_description": (
                "Requirement for technology product suppliers to make spare parts and repair "
                "information available for a minimum period post-sale (typically 7-10 years) "
                "and design products to be repairable, aligned with EU Right to Repair Directive."
            ),
            "category": "environmental",
            "policy_source": "EU Right to Repair Directive (2024/1799); UK Product Security and Telecommunications Infrastructure Act",
        },
        {
            "policy_name": "Responsible Minerals Initiative (RMI) — Cobalt and 3TG Sourcing",
            "policy_description": (
                "Supplier due diligence requirement on sourcing of cobalt, tin, tantalum, "
                "tungsten, and gold used in electronics; participation in the RMI Responsible "
                "Minerals Assurance Process (RMAP) for smelter/refiner validation."
            ),
            "category": "supply_chain",
            "policy_source": "Responsible Minerals Initiative (RMI); OECD Due Diligence Guidance for Responsible Mineral Supply Chains",
        },
        {
            "policy_name": "WCAG 2.1 Accessibility and EN 301 549 Compliance",
            "policy_description": (
                "Requirement for digital products and services to meet WCAG 2.1 Level AA "
                "accessibility standards and EN 301 549 (EU/UK ICT accessibility standard); "
                "mandatory for public sector buyers under the Public Sector Bodies Accessibility Regulations."
            ),
            "category": "social",
            "policy_source": "Web Content Accessibility Guidelines (WCAG) 2.1; EN 301 549; UK Public Sector Bodies (Websites and Mobile Applications) Accessibility Regulations 2018",
        },
        {
            "policy_name": "UK AI Ethics and Algorithmic Transparency",
            "policy_description": (
                "Requirement for technology suppliers deploying AI/ML systems to document "
                "algorithms, conduct bias and fairness testing, provide explainability to affected "
                "individuals, and align with the UK AI Regulation Pro-Innovation Framework."
            ),
            "category": "governance",
            "policy_source": "UK AI Regulation White Paper (DSIT, 2023); ICO Guidance on AI and Data Protection",
        },
        {
            "policy_name": "RE100 Commitment — 100% Renewable Electricity",
            "policy_description": (
                "Corporate commitment to source 100% of electricity consumption from renewable "
                "sources by a defined target year, verified annually through Renewable Energy "
                "Guarantees of Origin (REGOs) or equivalent energy attribute certificates."
            ),
            "category": "environmental",
            "policy_source": "RE100 Initiative (Climate Group and CDP)",
        },
        {
            "policy_name": "Gender Pay Gap Reporting (Equality Act 2010)",
            "policy_description": (
                "UK legal obligation for employers with 250+ staff to publish annual gender pay "
                "gap data including mean and median pay gaps, bonus gaps, and pay quartile "
                "proportions, alongside a narrative and action plan for closing the gap."
            ),
            "category": "social",
            "policy_source": "Equality Act 2010 (Gender Pay Gap Information) Regulations 2017",
        },
        {
            "policy_name": "B Corp Certification",
            "policy_description": (
                "Voluntary third-party certification requiring verified high standards across "
                "five impact areas: governance, workers, community, environment, and customers; "
                "increasingly required by enterprise buyers as a proxy for overall sustainability."
            ),
            "category": "certification",
            "policy_source": "B Lab (B Corp Certification)",
        },
    ],

    "Food & Beverage": [
        {
            "policy_name": "RSPO Roundtable on Sustainable Palm Oil Certification",
            "policy_description": (
                "Certification requirement for all palm oil and palm kernel oil in products to "
                "be sourced from RSPO-certified sustainable sources, with supply chain traceability "
                "to certified mills and an annual RSPO credits or supply chain model declaration."
            ),
            "category": "certification",
            "policy_source": "Roundtable on Sustainable Palm Oil (RSPO)",
        },
        {
            "policy_name": "Rainforest Alliance Certification for Coffee, Cocoa and Tea",
            "policy_description": (
                "Certification requirement for key commodity ingredients (coffee, cocoa, tea, "
                "bananas) to be sourced from Rainforest Alliance certified farms demonstrating "
                "biodiversity protection, fair worker treatment, and climate resilience."
            ),
            "category": "certification",
            "policy_source": "Rainforest Alliance (2020 Certification Programme)",
        },
        {
            "policy_name": "BRC Global Standard for Food Safety (Issue 9) / FSSC 22000",
            "policy_description": (
                "Food safety management certification requirement; all food manufacturing and "
                "processing suppliers must hold BRC AA/A Grade or FSSC 22000 certification "
                "covering hazard analysis, allergen management, traceability, and audit compliance."
            ),
            "category": "certification",
            "policy_source": "BRC Global Standards — Food Safety Issue 9; FSSC 22000 Version 6",
        },
        {
            "policy_name": "RSPCA Assured and Red Tractor Animal Welfare",
            "policy_description": (
                "For meat, dairy, egg, and fish ingredients: requirement that animal products "
                "are sourced from RSPCA Assured or Red Tractor accredited farms meeting "
                "UK higher welfare standards across housing, feeding, and slaughter."
            ),
            "category": "certification",
            "policy_source": "RSPCA Assured; Red Tractor Farm Assurance",
        },
        {
            "policy_name": "UK Plastics Pact and Packaging Recyclability Targets",
            "policy_description": (
                "Commitment to meet WRAP UK Plastics Pact 2025 targets: 100% reusable, "
                "recyclable, or compostable packaging; 70% packaging effectively recycled; "
                "30% average recycled content; and elimination of problematic plastics."
            ),
            "category": "environmental",
            "policy_source": "WRAP UK Plastics Pact (2018–2025)",
        },
        {
            "policy_name": "Fairtrade Certification",
            "policy_description": (
                "Supplier requirement for commodity sourcing (coffee, cocoa, tea, sugar, cotton, "
                "bananas) from Fairtrade-certified producer organisations, ensuring a guaranteed "
                "minimum price, Fairtrade Premium for community development, and fair labour standards."
            ),
            "category": "certification",
            "policy_source": "Fairtrade Foundation (UK); Fairtrade International Standards",
        },
        {
            "policy_name": "Antimicrobial Resistance (AMR) — Responsible Antibiotic Use in Livestock",
            "policy_description": (
                "Livestock supply chain requirement to phase out routine prophylactic antibiotic "
                "use, restrict highest-priority critically important antibiotics (HP-CIAs) to "
                "therapeutic use only, and publish farm-level antibiotic usage data annually."
            ),
            "category": "environmental",
            "policy_source": "UK Five Year National Action Plan on AMR 2024–2029; RUMA (Responsible Use of Medicines in Agriculture Alliance)",
        },
        {
            "policy_name": "Food Standards Agency Allergen Labelling (Natasha's Law)",
            "policy_description": (
                "UK legal requirement under the Food Information Regulations 2014 (amended 2021) "
                "for pre-packed for direct sale (PPDS) food to carry full ingredient lists with "
                "all 14 major allergens emphasised; requires validated allergen control procedures."
            ),
            "category": "governance",
            "policy_source": "UK Food Information (Amendment) Regulations 2019 ('Natasha's Law'); Food Standards Agency",
        },
        {
            "policy_name": "GFSI Recognised Certification and Food Fraud Prevention",
            "policy_description": (
                "Requirement for food suppliers to hold a Global Food Safety Initiative (GFSI) "
                "recognised certification (BRC, FSSC, SQF, IFS) incorporating food fraud "
                "vulnerability assessments, anti-counterfeiting controls, and recall procedures."
            ),
            "category": "certification",
            "policy_source": "Global Food Safety Initiative (GFSI); Consumer Goods Forum",
        },
        {
            "policy_name": "Courtauld Commitment 2030 Food Waste Reduction Targets",
            "policy_description": (
                "Voluntary but widely required commitment to achieve a 50% per capita reduction "
                "in food waste by 2030 (against a 2007 baseline), measured and reported through "
                "WRAP's methodology, covering waste in manufacturing, retail, and hospitality."
            ),
            "category": "environmental",
            "policy_source": "WRAP Courtauld Commitment 2030",
        },
        {
            "policy_name": "PAS 2050 Product Carbon Footprint Assessment",
            "policy_description": (
                "BSI standard for measuring the life cycle GHG emissions of products and "
                "services (cradle-to-grave or cradle-to-gate); increasingly required by retail "
                "buyers for carbon labelling and supply chain Scope 3 emissions reporting."
            ),
            "category": "reporting",
            "policy_source": "BSI PAS 2050:2011 (British Standards Institution)",
        },
        {
            "policy_name": "Zero Deforestation Commitment (Forest 500 / SBTN)",
            "policy_description": (
                "Supplier commitment to eliminate deforestation and land conversion from supply "
                "chains for high-risk commodities (palm oil, soy, beef, cocoa, timber) by 2025, "
                "with supply chain mapping and Forest 500 or SBTN-aligned verification."
            ),
            "category": "environmental",
            "policy_source": "Forest 500 (Global Canopy); Science Based Targets for Nature (SBTN)",
        },
    ],

    "Logistics & Transport": [
        {
            "policy_name": "FORS Fleet Operator Recognition Scheme Certification",
            "policy_description": (
                "UK certification scheme for fleet operators with three levels (Bronze, Silver, "
                "Gold); covers vehicle safety, driver competence, emissions management, and "
                "fuel efficiency — Bronze is mandatory for many London construction and public "
                "sector logistics contracts."
            ),
            "category": "certification",
            "policy_source": "FORS (Fleet Operator Recognition Scheme), Transport for London",
        },
        {
            "policy_name": "Zero Emission Vehicle (ZEV) Fleet Transition Commitment",
            "policy_description": (
                "Supplier commitment to transition fleet to zero emission vehicles on a defined "
                "timeline aligned with the UK Government Clean Van Commitment and ZEV mandate; "
                "requires annual reporting of fleet ZEV percentage and chargepoint deployment."
            ),
            "category": "environmental",
            "policy_source": "UK Government Zero Emission Vehicle (ZEV) Mandate; Clean Van Commitment",
        },
        {
            "policy_name": "Driver CPC Certificate of Professional Competence",
            "policy_description": (
                "UK legal requirement for all professional LGV/PCV drivers to hold a valid "
                "Driver Certificate of Professional Competence (Driver CPC), achieved through "
                "initial qualification and 35 hours of periodic training every 5 years."
            ),
            "category": "social",
            "policy_source": "UK Driver CPC (implementing EU Directive 2003/59/EC); DVSA",
        },
        {
            "policy_name": "EU/UK Working Time Regulations for Drivers (EC 561/2006)",
            "policy_description": (
                "Legal requirement for HGV and coach operators to comply with EU drivers' hours "
                "rules (EC 561/2006 as retained in UK law), mandatory rest periods, tachograph "
                "recording, and Working Time Directive limits of 48 hours per week averaged."
            ),
            "category": "social",
            "policy_source": "EC Regulation 561/2006 (retained UK law); UK Working Time Regulations 1998",
        },
        {
            "policy_name": "GHG Protocol Scope 3 Logistics Emissions Reporting",
            "policy_description": (
                "Requirement for logistics suppliers to measure and report transport-related "
                "GHG emissions using GHG Protocol Scope 3 Category 4 (upstream transport) "
                "and Category 9 (downstream transport) methodologies with annual disclosure."
            ),
            "category": "reporting",
            "policy_source": "WRI/WBCSD Greenhouse Gas Protocol — Scope 3 Standard; ISO 14083:2023",
        },
        {
            "policy_name": "Euro VI Heavy Duty Vehicle Emissions Standards",
            "policy_description": (
                "Regulatory requirement that all HGVs, buses, and coaches operated in the UK "
                "meet minimum Euro VI exhaust emission standards for NOx and PM; required for "
                "compliance with London ULEZ, Clean Air Zones, and public sector contracts."
            ),
            "category": "environmental",
            "policy_source": "EC Regulation 582/2011 (Euro VI, retained UK law); UK Clean Air Zones Framework",
        },
        {
            "policy_name": "ISO 14083 Quantification of GHG Emissions from Transport",
            "policy_description": (
                "International standard providing a common methodology for calculating and "
                "reporting GHG emissions across all transport modes; suppliers required to use "
                "ISO 14083-compliant calculations for client carbon reporting."
            ),
            "category": "reporting",
            "policy_source": "ISO 14083:2023 (International Organization for Standardization)",
        },
        {
            "policy_name": "F-Gas Regulation Compliance for Cold Chain Operations",
            "policy_description": (
                "UK/EU legal requirement for operators of refrigerated transport and cold "
                "storage to use F-Gas certified engineers, maintain leak detection and logbooks, "
                "and transition to lower-GWP refrigerants per the UK F-Gas phase-down schedule."
            ),
            "category": "environmental",
            "policy_source": "UK F-Gas Regulations 2014 (implementing EU F-Gas Regulation 517/2014)",
        },
        {
            "policy_name": "IATA / IMDG Dangerous Goods Handling Certification",
            "policy_description": (
                "Legal certification requirement for personnel and operators involved in the "
                "transport of dangerous goods: IATA Dangerous Goods Regulations for air, IMDG "
                "Code for sea, and ADR for road — with periodic retraining every two years."
            ),
            "category": "certification",
            "policy_source": "IATA Dangerous Goods Regulations; IMDG Code (IMO); ADR Agreement (UNECE)",
        },
        {
            "policy_name": "Modal Shift to Lower-Carbon Freight Modes",
            "policy_description": (
                "Procurement preference for logistics suppliers demonstrating active modal shift "
                "away from road freight toward rail, short-sea shipping, or inland waterway "
                "where feasible, with evidence of modal split and carbon reduction achieved."
            ),
            "category": "environmental",
            "policy_source": "UK Government Transport Decarbonisation Plan (2021); TfL Freight Sustainability Standards",
        },
    ],

    "Energy & Utilities": [
        {
            "policy_name": "Ofgem Net Zero Transition Plan and Decarbonisation Targets",
            "policy_description": (
                "Requirement for energy suppliers and network operators to publish credible net "
                "zero transition plans aligned with the UK Government's Energy Security Strategy, "
                "with interim 2030/2035 decarbonisation milestones and annual Ofgem reporting."
            ),
            "category": "environmental",
            "policy_source": "Ofgem Sustainability Reporting Framework; UK Energy Security Bill",
        },
        {
            "policy_name": "REGOs Renewable Energy Guarantees of Origin",
            "policy_description": (
                "UK certificate scheme proving that electricity supplied to customers is generated "
                "from eligible renewable sources; energy suppliers must hold sufficient REGOs "
                "to back any 'green' tariff claims and report annually to Ofgem."
            ),
            "category": "environmental",
            "policy_source": "Ofgem Renewables and CHP Register (REGOs); Electricity Act 1989",
        },
        {
            "policy_name": "ISO 50001:2018 Energy Management System",
            "policy_description": (
                "Certification requirement for large energy users and utilities to systematically "
                "monitor, measure, and reduce energy consumption; requires an energy policy, "
                "energy performance baselines, objectives, and documented improvement plans."
            ),
            "category": "certification",
            "policy_source": "ISO 50001:2018 (International Organization for Standardization)",
        },
        {
            "policy_name": "Environmental Permitting and Discharge Standards (EA)",
            "policy_description": (
                "Legal requirement for energy and water utilities to hold Environmental Permits "
                "from the Environment Agency (or SEPA/NRW), comply with effluent discharge "
                "quality limits (nitrogen, phosphorus, pollutants), and submit annual compliance reports."
            ),
            "category": "environmental",
            "policy_source": "Environmental Permitting (England and Wales) Regulations 2016; Environment Agency",
        },
        {
            "policy_name": "Biodiversity Net Gain Obligation (Environment Act 2021)",
            "policy_description": (
                "Legal requirement (effective November 2023) for developments above threshold "
                "size to achieve a mandatory 10% biodiversity net gain, assessed using the "
                "Biodiversity Metric 4.0 tool and secured through planning conditions or biodiversity gain plans."
            ),
            "category": "environmental",
            "policy_source": "UK Environment Act 2021 (Schedule 14); Natural England Biodiversity Net Gain Guidance",
        },
        {
            "policy_name": "Ofwat Water Efficiency and Leakage Reduction Targets",
            "policy_description": (
                "Regulatory requirement for water companies to meet Ofwat's Performance "
                "Commitments on leakage reduction (15% by 2025 against 2017/18 baseline), "
                "per capita consumption reduction, and resilient supply security under PR24."
            ),
            "category": "environmental",
            "policy_source": "Ofwat PR24 Price Review; Water Industry Act 1991",
        },
        {
            "policy_name": "Ofgem Customer Vulnerability Strategy and Fuel Poverty Standards",
            "policy_description": (
                "Regulatory requirement for energy suppliers to identify and support vulnerable "
                "customers (Priority Services Register, fuel poverty, debt), implement "
                "safeguards, and report outcomes against Ofgem's Consumer Vulnerability Strategy."
            ),
            "category": "social",
            "policy_source": "Ofgem Consumer Vulnerability Strategy 2025; Standards of Conduct",
        },
        {
            "policy_name": "UK F-Gas Phase-Down and HFC Refrigerant Compliance",
            "policy_description": (
                "UK regulatory requirement for energy and utilities operators to phase down "
                "high-GWP HFC refrigerants in line with the UK F-Gas phase-down schedule, "
                "use F-Gas certified engineers, and maintain leak detection and equipment logs."
            ),
            "category": "environmental",
            "policy_source": "UK F-Gas Regulations 2014; UK F-Gas phase-down schedule post-Brexit",
        },
        {
            "policy_name": "UK ETS Compliance for Energy Generation Installations",
            "policy_description": (
                "Mandatory cap-and-trade scheme requiring power generators and energy-intensive "
                "installations to monitor and report annual GHG emissions, and surrender "
                "sufficient UK ETS allowances by 30 April each year."
            ),
            "category": "environmental",
            "policy_source": "UK Emissions Trading Scheme (UK ETS); UK ETS Authority",
        },
        {
            "policy_name": "Smart Meter Rollout Obligations (SMETS2 Compliance)",
            "policy_description": (
                "Regulatory obligation for energy suppliers to take all reasonable steps to "
                "install second-generation smart meters (SMETS2) for domestic and SME customers, "
                "report quarterly to BEIS/Ofgem, and meet annual installation targets."
            ),
            "category": "governance",
            "policy_source": "UK Smart Metering Implementation Programme; Smart Meters Act 2018",
        },
    ],

    "Professional Services": [
        {
            "policy_name": "OECD Guidelines Human Rights and Labour Due Diligence",
            "policy_description": (
                "Requirement for professional services firms to conduct human rights due diligence "
                "covering own operations, supply chains (outsourced services, contractors), "
                "and client advisory work; aligned with the UN Guiding Principles on Business and Human Rights."
            ),
            "category": "social",
            "policy_source": "OECD Guidelines for Multinational Enterprises (2023 update); UN Guiding Principles on Business and Human Rights",
        },
        {
            "policy_name": "UK Bribery Act 2010 Adequate Procedures",
            "policy_description": (
                "UK legal requirement for professional services firms to implement adequate "
                "anti-bribery procedures covering policies, due diligence, communication, "
                "monitoring, and top-level commitment — the statutory defence against liability."
            ),
            "category": "governance",
            "policy_source": "UK Bribery Act 2010; Ministry of Justice Guidance on Adequate Procedures",
        },
        {
            "policy_name": "ISO 27001 Information Security Management System",
            "policy_description": (
                "International standard for information security management; required by "
                "enterprise and public sector clients for professional services firms handling "
                "sensitive data, covering risk assessment, controls, and incident management."
            ),
            "category": "certification",
            "policy_source": "ISO/IEC 27001:2022 (International Organization for Standardization)",
        },
        {
            "policy_name": "Gender Pay Gap Reporting (Equality Act 2010)",
            "policy_description": (
                "UK legal obligation for employers with 250+ employees to publish annual gender "
                "pay gap data including mean and median pay gaps, bonus gaps, and pay quartile "
                "proportions, with a narrative and action plan for closing the gap."
            ),
            "category": "social",
            "policy_source": "Equality Act 2010 (Gender Pay Gap Information) Regulations 2017",
        },
        {
            "policy_name": "Ethnicity Pay Gap and DEI Representation Reporting",
            "policy_description": (
                "Voluntary but increasingly required by public sector clients: firms should "
                "measure and publish ethnicity pay gap, set representation targets for senior "
                "roles, and participate in the Social Mobility Index or equivalent benchmarks."
            ),
            "category": "social",
            "policy_source": "UK Government Ethnicity Pay Gap Reporting Guidance (DCMS, 2023); Social Mobility Commission",
        },
        {
            "policy_name": "Carbon Footprint Measurement and SBTi Target Setting",
            "policy_description": (
                "Requirement for professional services firms to measure Scope 1, 2, and material "
                "Scope 3 emissions (primarily business travel and supply chain), set SBTi-validated "
                "reduction targets, and report annually through CDP or equivalent."
            ),
            "category": "environmental",
            "policy_source": "Science Based Targets initiative (SBTi); CDP Climate Questionnaire",
        },
        {
            "policy_name": "Continuing Professional Development (CPD) Requirements",
            "policy_description": (
                "Requirement for professional services firms to maintain staff CPD aligned with "
                "relevant professional body standards (Law Society, ICAEW, RIBA, CIPD, etc.), "
                "including growing requirements for sustainability and climate-related CPD hours."
            ),
            "category": "governance",
            "policy_source": "Law Society CPD Requirements; ICAEW CPD Framework; RIBA CPD Core Curriculum",
        },
        {
            "policy_name": "ISO 9001:2015 Quality Management System",
            "policy_description": (
                "International quality management certification; required by many public sector "
                "and enterprise buyers as a baseline for professional services suppliers, "
                "covering client focus, risk-based thinking, and continual improvement."
            ),
            "category": "certification",
            "policy_source": "ISO 9001:2015 (International Organization for Standardization)",
        },
        {
            "policy_name": "B Corp Certification",
            "policy_description": (
                "Voluntary certification increasingly required by impact-focused clients; "
                "requires verified high standards across governance, workers, community, "
                "environment, and customers — with recertification every three years."
            ),
            "category": "certification",
            "policy_source": "B Lab (B Corp Certification)",
        },
        {
            "policy_name": "HSE Workplace Wellbeing and Mental Health Standards",
            "policy_description": (
                "Requirement for professional services employers to implement HSE's Management "
                "Standards for work-related stress, provide confidential employee assistance "
                "programmes, and report on staff wellbeing metrics; increasingly measured in "
                "procurement ESG assessments."
            ),
            "category": "social",
            "policy_source": "HSE Management Standards for Work-related Stress; ISO 45003:2021",
        },
    ],
}

DEFAULT_INDUSTRIES = list(CURATED_POLICIES.keys())


# ---------------------------------------------------------------------------
# BigQuery helpers
# ---------------------------------------------------------------------------

def ensure_table(bq_client: bigquery.Client) -> None:
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    try:
        bq_client.get_table(table_ref)
        print(f"Table {table_ref} already exists.")
    except Exception:
        table = bigquery.Table(table_ref, schema=POLICY_SCHEMA)
        bq_client.create_table(table)
        print(f"Created table {table_ref}.")


def get_existing_policy_names(bq_client: bigquery.Client, industry: str) -> set[str]:
    query = f"""
        SELECT LOWER(policy_name) as pname
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        WHERE LOWER(industry) = @industry
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("industry", "STRING", industry.lower())]
    )
    try:
        results = bq_client.query(query, job_config=job_config).result()
        return {row.pname for row in results}
    except Exception:
        return set()


def insert_policies(
    bq_client: bigquery.Client,
    industry: str,
    policies: list[dict],
    dry_run: bool,
) -> int:
    existing = get_existing_policy_names(bq_client, industry)
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for p in policies:
        name = p.get("policy_name", "").strip()
        if not name or name.lower() in existing:
            continue
        rows.append({
            "policy_id": str(uuid.uuid4()),
            "industry": industry,
            "policy_name": name,
            "policy_source": p.get("policy_source", ""),
            "policy_description": p.get("policy_description", ""),
            "category": p.get("category", ""),
            "last_updated": now,
        })

    if not rows:
        print(f"  No new policies to insert for {industry} (all already present).")
        return 0

    if dry_run:
        print(f"  [dry-run] Would insert {len(rows)} policies for {industry}:")
        for r in rows:
            print(f"    - [{r['category']}] {r['policy_name']}  |  {r['policy_source']}")
        return len(rows)

    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    errors = bq_client.insert_rows_json(bq_client.get_table(table_ref), rows)
    if errors:
        print(f"  BigQuery insert errors for {industry}: {errors}")
        return 0

    print(f"  Inserted {len(rows)} new policies for {industry}.")
    return len(rows)


# ---------------------------------------------------------------------------
# Optional LLM supplementation
# ---------------------------------------------------------------------------

def search_policy_sources(industry: str) -> list[dict]:
    """Return {title, snippet, url} from Google Search for additional grounding."""
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_CX:
        print(f"  [search] No Google Search credentials — skipping web search for {industry}")
        return []

    queries = [
        f"{industry} industry procurement sustainability requirements UK 2024",
        f"{industry} supplier sustainability certification procurement criteria UK",
    ]
    results = []
    for q in queries:
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": GOOGLE_SEARCH_API_KEY, "cx": GOOGLE_SEARCH_CX, "q": q, "num": 5},
                timeout=10,
            )
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                results.append({
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "url": item.get("link", ""),
                })
        except Exception as e:
            print(f"  [search] Query failed ({q!r}): {e}")
        time.sleep(0.5)
    return results


def supplement_with_llm(
    industry: str,
    existing_names: list[str],
    search_results: list[dict],
    gemini_client: genai.Client,
) -> list[dict]:
    """
    Ask Gemini to suggest additional policies NOT already covered by the curated list.
    Only call this when --supplement-with-llm is passed.
    """
    search_context = ""
    if search_results:
        snippets = "\n".join(
            f"- [{r['title']}] ({r['url']}): {r['snippet']}" for r in search_results[:8]
        )
        search_context = f"\nWeb search results to ground your response:\n{snippets}\n"

    existing_list = "\n".join(f"- {n}" for n in existing_names)

    prompt = f"""You are an expert in UK and international sustainability procurement standards.

The following procurement policies for the {industry} industry are ALREADY in our database:
{existing_list}

Your task: suggest additional procurement policies for the {industry} industry that are NOT in the list above.
Only include policies that are REAL, currently active standards, regulations, or certification schemes.
Do NOT suggest policies that are vague, invented, or unverifiable.{search_context}

Return 5-10 additional policies. For each provide:
- policy_name: exact name of the standard or requirement
- policy_description: 1-2 sentences on what the requirement actually entails
- category: one of [environmental, social, governance, supply_chain, reporting, certification]
- policy_source: the exact standard number, regulation, or organisation name

Return ONLY valid JSON:
{{
  "policies": [
    {{
      "policy_name": "...",
      "policy_description": "...",
      "category": "...",
      "policy_source": "..."
    }}
  ]
}}"""

    for attempt in range(3):
        try:
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=GenerateContentConfig(response_mime_type="application/json"),
            )
            return json.loads(response.text).get("policies", [])
        except Exception as e:
            print(f"  [llm] Attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                return []
            time.sleep(2 ** attempt)
    return []


# ---------------------------------------------------------------------------
# Per-industry orchestration
# ---------------------------------------------------------------------------

def populate_industry(
    industry: str,
    bq_client: bigquery.Client,
    gemini_client: genai.Client | None,
    dry_run: bool,
    use_llm_supplement: bool,
) -> int:
    print(f"\nProcessing: {industry}")

    curated = UNIVERSAL_POLICIES + CURATED_POLICIES.get(industry, [])
    print(f"  {len(curated)} curated policies ({len(UNIVERSAL_POLICIES)} universal + {len(curated) - len(UNIVERSAL_POLICIES)} industry-specific)")

    inserted = insert_policies(bq_client, industry, curated, dry_run)

    if use_llm_supplement and gemini_client is not None:
        existing_names = [p["policy_name"] for p in curated]
        search_results = search_policy_sources(industry)
        print(f"  Running LLM supplementation ({len(search_results)} search results found)...")
        extra = supplement_with_llm(industry, existing_names, search_results, gemini_client)
        print(f"  LLM suggested {len(extra)} additional policies.")
        inserted += insert_policies(bq_client, industry, extra, dry_run)

    return inserted


def main():
    parser = argparse.ArgumentParser(description="Populate procurement_policies BigQuery table.")
    parser.add_argument(
        "--industries",
        type=str,
        default=None,
        help="Comma-separated list of industries (default: all curated industries)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be inserted without writing to BigQuery",
    )
    parser.add_argument(
        "--supplement-with-llm",
        action="store_true",
        help="After inserting curated policies, run a Gemini pass to suggest additional ones",
    )
    args = parser.parse_args()

    industries = (
        [i.strip() for i in args.industries.split(",")]
        if args.industries
        else DEFAULT_INDUSTRIES
    )

    bq_client = bigquery.Client(project=PROJECT_ID)
    gemini_client = None
    if args.supplement_with_llm:
        gemini_client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")

    if not args.dry_run:
        ensure_table(bq_client)

    total_inserted = 0
    for industry in industries:
        total_inserted += populate_industry(
            industry,
            bq_client,
            gemini_client,
            dry_run=args.dry_run,
            use_llm_supplement=args.supplement_with_llm,
        )

    print(f"\nDone. Total policies inserted: {total_inserted}")


if __name__ == "__main__":
    main()
