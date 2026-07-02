# SaaS Env World principles


## Requirements

* Simulation specific ellapsed time. 
* The interface to help an agent interact with environment basically reset environment, state and action. 
* Providing main character which is interface and for coworkers with secondary activities.
* There must be multiple scenarios for the agent to work on that include blockers, resolve conflicts, prioritize tradeoffs.
    * Have a clear goal to strive for as a PM, to be able to assess a right / wrong decision from a ground truth.

* Company State
    * Coworkers
        * CEO 
            * CFO
                * Revenue Ops Analyst
            * CTO
                * PM A -- ** Target Agent
                    * FE Eng A1
                * PM B
                    * Fullstack Eng B1
                    * BE Eng B2
                    * BE Eng B3
                * Designer
                * SRE / DevOps Engineer
            * COO
                * BizOps 
                * Head of Sales
                    * AE 1
                    * AE 2
                    * SDR Manager
                        * SDR 1
                        * SDR 2
                        * SDR 3
                        * SDR 4
                        * SDR 5
                * Customer Support Manager 1
                    * CS Support 1
                    * CS Support 2
    * [Future] Customers
        * 35 tier-1 customers (generate 70% of revenue)
        * 80 tier-2 customers (generate 25% of revenue)
        * 50 tier-3 customers (generate 5% of revenue)


## Design Decisions

* World State Representation
    * Company Structure
        * [Future] Team status (health, vacation, leaves, seniority, time in the company)
    * Stage of Company
        * [Future] Financial metrics 
        * [Future] Customer adoption metrics
            * Customers list (description, account type, usage)
        * Projects
    * [Future] Seasonality (historical sales cycles, industry events)

