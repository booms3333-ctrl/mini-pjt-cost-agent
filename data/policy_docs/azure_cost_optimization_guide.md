# Azure 공식 비용 최적화 가이드

- 출처: Azure 공식 문서 (Well-Architected Framework, 인증 불필요)
- 스냅샷 생성일: 2026-09-17
- 이 문서는 scripts/fetch_cost_optimization_guides.py가 아래 공식 URL에서 자동으로 가져온 스냅샷이다. 최신 내용은 원본 링크를 참고하라.

## 설계 원칙
(출처: https://learn.microsoft.com/en-us/azure/well-architected/cost-optimization/principles)

Table of contents
Exit editor mode
Ask Learn
Ask Learn
Reading mode
Table of contents
Read in English
Add
Add to Plans
Edit
Copy Markdown
Print
Note
Access to this page requires authorization. You can try
signing in
or
changing directories
.
Access to this page requires authorization. You can try
changing directories
.
Cost Optimization design principles
Feedback
Summarize this article for me
Architecture design is always driven by business goals and must
factor in return on investment (ROI) and financial constraints
. Typical questions to consider include:
Do the allocated budgets enable you to meet your goals?
What's the spending pattern for the application and its operations? What are priority areas?
How will you maximize the investment in resources, by better utilization or by reduction?
A cost-optimized workload isn't necessarily a low-cost workload. There are significant tradeoffs. Tactical approaches are reactive and can reduce costs only in the short term. To achieve long-term financial responsibility, you need to
create a strategy with prioritization, continuous monitoring, and repeatable processes
that focuses on optimization.
The design principles are intended to provide optimization strategies that you need to consider when you design and implement your workload architecture. Start with the recommended approaches and
justify the benefits for a set of business requirements
. After you set your strategy, drive actions by using the
Cost Optimization checklist
as your next step.
As you prioritize business requirements to align with technology needs, expect the initial cost allocation to change. However, you should expect a series of tradeoffs in areas in which you want to optimize cost, such as security, scalability, resilience, and operability. If the cost of addressing the challenges in those areas is high and these principles aren't applied properly, you might make risky choices in favor of a cheaper solution, ultimately affecting your organization's business goals and reputation.
Develop cost-management discipline
Build a team culture that has awareness of budget, expenses, reporting, and cost tracking.
Cost optimization is conducted at various levels of the organization. It's important to understand how your workload cost is aligned with organizational FinOps practices. A view into the business units, resource organization, and centralized audit policies allows you to adopt a standardized financial system.
Approach
Benefit
Develop a cost model. This fundamental exercise is a prerequisite to setting up a financial tracking system.
A cost model helps segment expenses and estimate and forecast the total cost of ownership, including infrastructure, support, and implementation. It enables you to identify cost drivers early and predict how any change, growth, or shrinkage will affect overall spending in your projected business model.
Have an effective but flexible accountability model that's governed and implemented with properly assigned roles and responsibilities.
Clear accountability helps enforce the functional expectations of each role (given a scope), drive clarity, and generate reports with transparency at desired levels.
Proactive governance can help you avoid actions that might lead to unnecessary expenditure that's beyond the budget.
Estimate realistic budgets that cover all non-negotiable functional and nonfunctional requirements, personnel, and processes that provide for anticipated growth.
You'll be able to set financial boundaries and establish ways to check your spending against the allocated budget. You'll also get notifications when certain thresholds are exceeded, which prevents overspending at the tenant scope, resource scope, and other scopes that are applied to the budget.
For workloads governed by service-level agreements (SLAs), evaluate whether to allocate budget toward potential penalties or toward implementation efforts.
A well-implemented solution can help you avoid penalties altogether, making proactive investment.
Setting aside a customer compensation budget is a pragmatic approach to reduce the risk of future liability. Collaborate with your product owner to negotiate realistic cost compensation budget.
Plan on training costs, hiring expenses, and the cost of infrastructure needed to augment skills as the workload matures.
Investing in staffing complements existing skills through full-time or vendor support.
Communicate cost implications of design changes that are driven by insights gained from production.
The organization is able to make practical budget adjustment based on production feedback, which should be considered as meaningful as numeric data.
Design with a cost-efficiency mindset
Spend only on what you need to achieve the highest return on your investments.
Every architectural decision has direct and indirect financial implications. Understand the costs associated with build versus buy options, technology choices, the billing model and licensing, training, operations, and so on.
Given a set of requirements, optimize, and make tradeoff decisions, in relation to costs, that still effectively address the cross-cutting concerns of the workload.
Approach
Benefit
Establish a cost baseline, including the projected growth. Ensure design choices work within the allocated budget to meet the functional and nonfunctional requirements.
Factor in expenses related to technology choices, automation, acquisition, training, and change management as part of that total cost.
Cost estimates enable you to forecast expenses against the budget and pinpoint key cost drivers. They also help reveal hidden costs that might otherwise go unnoticed, supporting a balanced approach that avoids overengineering.
This process will also generate decision trees for technology options based on cost considerations. By eliminating high-cost alternatives that lack strong business justification, you can free up budget capacity to invest in higher-value opportunities.
We don't recommend that you design beyond planned growth as it may result in a lower ROI.
Design and enforce cost guardrails in your architecture that keep the resources within the upper and lower limits.
Enforcement can prevent incidental or unapproved charges and ensure that only budgeted quantity of resources are provisioned.
Treat different SDLC environments differently, and deploy the right number of environments.
You can save money by understanding that not all environments need to simulate production. Nonproduction environments can have different features, SKUs, instance counts, and even logging.
You also can save costs by creating preproduction environments on-demand and removing them when you no longer need them.
Design for usage optimization
Maximize the use of resources and operations. Apply them to the negotiated functional and nonfunctional requirements of the solution.
Services and offerings provide various capabilities and pricing tiers. After you purchase a set of features, avoid underutilizing them. Find ways to maximize your investment in the tier. Likewise, continuously evaluate billing models to find those that better align to your usage, based on current production workloads.
Approach
Benefit
Take advantage of the full capabilities of your selected resource SKUs to meet performance, security, reliability, and operational goals.
You can maximize the use of what you paid for. Avoid selecting SKUs with features you don't need, as they can lead to unnecessary costs without added benefit.
Evaluate opportunities to dynamically adjust capacity, scaling up when demand increases and scaling down when it's no longer needed.
Without this approach, you may need to pre-provision more capacity than necessary.  By contrast, dynamic scaling enables you to maintain a minimum baseline and expand only when required, aligning resource consumption with actual usage patterns.
Prioritize deployment of active-active models over active-passive models, as part of your recovery plan, if you already paid for the resources.
If your design defaults to using active-passive models, you might have idle resources that could otherwise be used. Converting to active-active might enable you to meet your load leveling and scale bursting requirements without overspending.
Prioritize the use of commitment-based discounted resources when developing new features, setting up additional environments, or optimizing for nonfunctional requirements.
Finding opportunities to use committed plans can significantly reduce the cost of implementing new functionality.
Make the most of your investment in a support plan.
Keep allowance for training to ensure the team are using relevant tools and technologies.
Using your support plan to handle production problems or for proactive reviews will help you get your money's worth. Fully engage with your Microsoft support model.
Design for rate optimization
Increase efficiency without redesigning, renegotiating, or sacrificing functional or nonfunctional requirements.
Take advantage of opportunities to optimize the utility and costs of your existing resources and operations. If you don't, you unnecessarily spend money without any added ROI.
Approach
Benefit
Identify resources that have stable or predictable usage patterns over time. Optimize costs by prepurchasing these resources to take advantage of available discounts.
Collaborate with your licensing team to influence future purchasing agreements and renewal strategies.
Microsoft offers discounted rates for predictable, long-term commitments to specific resources or resource categories. These resources incur lower costs during the usage period and can be amortized over time.
By keeping your licensing team informed about current and projected resource investments, you can help them right-size commitments during agreement negotiations. In some cases, these forecasts can influence your organization's price sheet, benefiting not only your workload's cost efficiency but also other teams using the same technologies.
Explore alternatives that don't require additional licensing. Consider options like hybrid use and preproduction subscription pricing.
You'll be able to reduce licensing costs by taking advantage of options that give you usage rights to the same or comparable technologies at a lower cost.
Use consumption-based pricing when it's more cost effective.
You'll pay for what you use. This option might be more expensive than a fully utilized prepaid option. However, if you don't expect to fully utilize pre-purchased compute, pay-as-you-go might be a better choice.
Use fixed-price billing instead of consumption-based billing for a resource when its utilization is high and predictable and a comparable SKU or billing option is available.
When utilization is high and predictable, the fixed-price model usually costs less and often supports more features.
Where possible, co-locate usage with other workloads, resources, and teams to reduce financial and operational costs.
Shared resources are managed centrally and provisioned with higher capacity to support multiple workloads, allowing costs to be distributed across teams.
Deploy to lower-cost regions, provided there are no compromises to functional or nonfunctional requirements.
Evaluate regional options for each environment individually. While production may require specific regions, consider leveraging more cost-effective regions for preproduction environments where feasible.
Use premium regions only where necessary can lead to significant savings. Also, savings from non-production environments can be reallocated to other priorities.
Prefer services that make it easier to achieve higher density.
Consider the potential tradeoffs, especially on security boundaries.
As density increases, the amount of resources that you need to run a workload decreases. This decrease reduces cost per unit and the cost of management.
Monitor and optimize over time
Continuously right-size investment as your workload evolves with the ecosystem.
What was important yesterday might not be important today. As you learn through evaluation of production workloads, expect changes in architecture, business requirements, processes, and even team structure. Your software development lifecycle (SDLC) practices might need to evolve. External factors might also change, like the cloud platform, its resources, and your agreements.
You should carefully assess the impact of all changes on cost. Monitor changes and the ROI trend on a regular cadence, and evaluate whether you need to adjust functional and nonfunctional requirements.
Approach
Benefit
Build capabilities in the system that capture and classify expense.
You'll be able to calculate the costs that reveal technical and business perspectives at different billing boundaries.
You'll also be able to conduct regular reviews and drive showback and chargeback processes.
Implement cost alerts when spending approaches predefined budget thresholds.
Regularly review and adjust these alerts to ensure they remain aligned with evolving usage patterns.
Proactive notifications help prevent budget overruns and support timely decision-making.
Continuously evaluate and adjust architecture design decisions around cost of resources, operations, and paid support.
Regular reviews of metrics, performance data, billing reports, and feature usage might lead to fine-tuning that can reduce costs.
You might also be able to save some costs by evaluating the use of your support contract and right-sizing it.
Decommission resources that are underutilized, unused, obsolete, or can be replaced with more efficient alternatives.
Regularly delete unnecessary data.
By resizing or removing underutilized resources, or even changing SKUs, you can reduce costs. Shutting down unused resources and deleting data when you no longer need it reduces waste and frees up funds so you can invest them elsewhere.
Next steps
Cost Optimization checklist
Feedback
Was this page helpful?
Yes
No
No
Need help with this topic?
Want to try using Ask Learn to clarify or guide you through this topic?
Ask Learn
Ask Learn
Suggest a fix?
Additional resources
Last updated on
2025-05-29

## 체크리스트
(출처: https://learn.microsoft.com/en-us/azure/well-architected/cost-optimization/checklist)

Table of contents
Exit editor mode
Ask Learn
Ask Learn
Reading mode
Table of contents
Read in English
Add
Add to Plans
Edit
Copy Markdown
Print
Note
Access to this page requires authorization. You can try
signing in
or
changing directories
.
Access to this page requires authorization. You can try
changing directories
.
Design review checklist for Cost Optimization
Feedback
Summarize this article for me
This checklist presents a set of recommendations about cost optimization for your workload to help you achieve a high return on investment (ROI) based on the business value that your workload delivers. Cost optimization balances actual costs versus perceived value, team efficiency, focus, and effort, while meeting the defined functional and nonfunctional requirements of your workload.
Every workload has direct and indirect costs, and every workload is designed to deliver value. If you don't incorporate the recommendations in this article and consider the tradeoffs, your design might not make the best use of your time and money. Carefully consider the points covered in the following checklist to instill confidence in your design's success.
Cost optimization is a continuous process in which you optimize workload costs and align your workload with the broader governance discipline of cost management. What's important today might not be important tomorrow. Technology choices or options and features that your platform offers today might be different. Learn from production and nonproduction environments, be aware of platform changes, and apply your findings to your workload and your workload's dependencies.
Checklist
Code
Recommendation
â
CO:01
Create a culture of financial responsibility.
Regularly train personnel so technical skills remain sharp. Foster creativity and spending accountability in the work environment. Invest in tooling and implementing automation.
â
CO:02
Create and maintain a cost model.
A cost model should estimate the initial cost, run rates, and ongoing costs. Negotiate a budget that covers a cost model and has a buffer for unplanned spending.
â
CO:03
Collect and review cost data.
Data collection should capture daily costs. In cost reports, include incurred costs (metered), prepaid costs (amortized), trends, and forecasts. Stakeholders should regularly review spending against the budget and cost model. Automate alerts to trigger notifications at key thresholds and detect anomalies to indicate deviations from trend baselines.
â
CO:04
Set spending guardrails.
Guardrails should include release gates, governance policies, resource limits, and access controls. Prioritize platform automation over manual processes.
â
CO:05
Get the best rates from providers.
You should find and use the best rates for cloud resources and licenses. Regularly review cost savings. Cost reviews should include regional pricing, pricing tiers, pricing models (consumption or commitment-based), license portability, corporate purchasing plans, and price sheets.
â
CO:06
Align usage to billing increments.
You should understand billing increments (meters) and align resource usage to those increments. Modify the service to align with billing increments, or modify resource usage to align with billing increments. Consider using a proof-of-concept to validate billing knowledge and design choices for major cost drivers and to reveal ways to align billing and resource usage.
â
CO:07
Optimize component costs.
Regularly remove or optimize legacy, unneeded, and underutilized workload components, including application features, platform features, and resources.
â
CO:08
Optimize environment costs.
Align spending to prioritize preproduction, production, operations, and disaster recovery environments. For each environment, consider the required availability, licensing, operating hours and conditions, and security. Nonproduction environments should emulate the production environment. Implement strategic tradeoffs into nonproduction environments.
â
CO:09
Optimize flow costs.
Align the cost of each flow with flow priority. When you prioritize flows, consider the features, functionality, and nonfunctional requirements of each flow. Optimizing flow spend often requires strategic compromises.
â
CO:10
Optimize data costs.
Data spending with data priority. Data optimization should include improvements to data management (tiering and retention), volume, replication, backups, file formats, and storage solutions.
â
CO:11
Optimize code costs.
Evaluate and modify code to meet functional and nonfunctional requirements with fewer or cheaper resources.
â
CO:12
Optimize scaling costs.
Evaluate alternative scaling within your scale units. Consider alternative scaling configurations, and align with the cost model. Considerations should include utilization against the inherit limits of every instance, resource, and scale unit boundary. Use strategies for controlling demand and supply.
â
CO:13
Optimize personnel time.
Align the time personnel spends on tasks with the priority of the task. The goal is to reduce the time spent on tasks without degrading the outcome. Optimization efforts should include minimizing noise, reducing build times, high fidelity debugging, and production mocking.
â
CO:14
Consolidate resources and responsibility.
Look within the workload for ways to consolidate resources and increase density. Outside the workload, use existing centralized resources and services that enable you to consolidate workload responsibilities.
Next steps
We recommend that you review the Cost Optimization tradeoffs to explore other concepts.
Cost Optimization tradeoffs
Feedback
Was this page helpful?
Yes
No
No
Need help with this topic?
Want to try using Ask Learn to clarify or guide you through this topic?
Ask Learn
Ask Learn
Suggest a fix?
Additional resources
Last updated on
2023-11-15

## 트레이드오프
(출처: https://learn.microsoft.com/en-us/azure/well-architected/cost-optimization/tradeoffs)

Table of contents
Exit editor mode
Ask Learn
Ask Learn
Reading mode
Table of contents
Read in English
Add
Add to Plans
Edit
Copy Markdown
Print
Note
Access to this page requires authorization. You can try
signing in
or
changing directories
.
Access to this page requires authorization. You can try
changing directories
.
Cost Optimization tradeoffs
Feedback
Summarize this article for me
When you design a workload to maximize return on investment (ROI) under financial constraints, you first need clearly defined functional and nonfunctional requirements. A work and effort prioritization strategy is essential. The foundation is a team that has a strong sense of financial responsibility. The team should have a strong understanding of available technologies and their billing models.
After you understand the ROI of a workload, you can start improving it. Consider how decisions based on the
Cost Optimization design principles
and the recommendations in the
Design review checklist for Cost Optimization
might influence the goals and optimizations of other Well-Architected Framework pillars. For cost optimization, it's important to avoid focusing on a cheaper solution. Choices that focus only on minimizing spending can undermine your workload's business goals and reputation. This article describes example tradeoffs that a workload team might encounter when setting targets, designing, and planning operations for cost optimization.
Cost Optimization tradeoffs with Reliability
The cost of a service disruption must be measured against the cost of preventing or recovering from one. If the cost of disruptions exceeds the cost of reliability design, you should invest more to prevent or mitigate disruptions. Conversely, the cost of the reliability efforts might be more than the cost of a disruption, including factors like compliance requirements and reputation. You should consider strategic divestment in reliability design only in this scenario.
Tradeoff: Reduced resiliency.
A workload incorporates resiliency measures to attempt to avoid and withstand specific types and quantities of malfunction.
To save money, the workload team might underprovision a component or overconstrain its scaling, making the component more likely to fail during sudden spikes in demand.
Consolidating workload resources (
increasing density
) for cost optimization makes individual components more likely to fail during spikes in demand and during maintenance operations like updates.
Removing components that support resiliency design patterns, like a message bus, and creating a direct dependency reduces self-preservation capabilities.
Saving money by reducing redundancy can limit a workload's ability to handle concurrent malfunctions.
Using budget SKUs might limit the maximum service-level objective (SLO) that the workload can reach.
Setting hard spending limits can prevent a workload from scaling to meet legitimate demand.
Without reliability testing tools or tests, the reliability of a workload is unknown, and it's less likely to meet reliability targets.
Tradeoff: Limited recovery strategy.
A workload that's reliable has a tested incident response and recovery plan for disaster scenarios.
Reduced testing or drilling of a workload's disaster recovery plan might affect the speed and effectiveness of recovery operations.
Creating or retaining fewer backups decreases possible recovery points and increases the chance of losing data.
Choosing a less expensive support contract with technology partners might increase workload recovery time due to potential delays in technical assistance.
Tradeoff: Increased complexity.
A workload that uses straightforward approaches and avoids unnecessary or overengineered complexity is generally easier to manage in terms of reliability.
Using cost-optimization cloud patterns can add new components, like a content delivery network (CDN), or shift duties to edge and client devices that a workload must provide reliability targets for.
Event-based scaling can be more complicated to tune and validate than resource-based scaling.
Reducing data volume and tiering data through data lifecycle actions, possibly in conjunction with implementing aggregated data points before a lifecycle event, introduces reliability factors to consider in the workload.
Using different regions to optimize cost can make management, networking, and monitoring more difficult.
Cost Optimization tradeoffs with Security
The cost of a compromise to confidentiality, integrity, or availability must always be balanced against the cost of preventing it. A security incident can cause significant financial, legal, and reputational harm. Investing in security mitigates risk, and that investment must be measured against the cost of experiencing the risk. As a rule, don't compromise on security to gain cost optimizations that are below the point of responsible and agreed upon risk mitigation. Optimizing security costs by rightsizing solutions is an important optimization practice, but be aware of tradeoffs like the following when doing so.
Tradeoff: Reduced security controls.
Security controls are established across multiple layers, sometimes redundantly, to provide defense in depth.
One cost optimization tactic is to look for ways to remove components or processes that accrue unit or operational costs. Removing security components like the following examples for the sake of saving money impacts security. You need to carefully perform a risk analysis on this impact.
Reducing or simplifying authentication and authorization techniques compromises the
verify explicitly
principle of Zero Trust architecture. Examples of these simplifications include using a basic authentication scheme like preshared keys rather than investing time to learn industry OAuth approaches, or using simplified role-based access control assignments to reduce management overhead.
Removing encryption in transit or at rest to reduce costs on certificates and their operational processes exposes data to potential integrity or confidentiality breaches.
Removing or reducing security scanning, inspection tooling, or security testing because of the associated cost and time investment can directly affect the confidentiality, integrity, or availability that those tools and tests are intended to protect.
Reducing the frequency of security patching to save operational time on cataloging and applying patches affects a workload's ability to address evolving threats.
Removing network controls like firewalls might lead to a failure to block malicious inbound and outbound traffic.
Tradeoff: Increased workload surface area.
The Security pillar prioritizes a reduced and contained surface area to minimize attack vectors and the management of security controls.
Cloud design patterns that optimize costs sometimes necessitate the introduction of additional components. These additional components increase the surface area of the workload. The components and the data within them must be secured, possibly in ways that aren't already used in the system. These components and data are often subject to compliance. Examples of patterns that can introduce components include:
Using the Static Content Hosting pattern to offload data to a new CDN component.
Using the Valet Key pattern to offload processing and secure resource access to client compute.
Using the Queue-Based Load Leveling pattern to smooth costs by introducing a message bus.
Tradeoff: Removed segmentation.
The Security pillar prioritizes strong segmentation to support the application of targeted security controls and to control the blast radius.
Sharing resources, for example in multitenancy situations or co-locating multiple applications on a shared application platform, is an approach for reducing costs by increasing density and reducing the management surface. This increased density can lead to security concerns like these:
Lateral movement between components that share resources is easier. A security event that compromises the availability of the application platform host or an individual application also has a larger blast radius.
Co-located resources might share a workload identity and have less meaningful audit trails in access logs.
Network security controls must be broad enough to cover all co-located resources. This configuration potentially violates the principle of least privilege for some resources.
Co-locating disparate applications or data on a shared host can lead to extending compliance requirements and security controls to applications or data that would otherwise be out of scope. This broadening of scope necessitates additional security scrutiny and auditing effort on the co-located components.
Cost Optimization tradeoffs with Operational Excellence
Tradeoff: Compromised software development lifecycle (SDLC) capacities.
A workload's SDLC process provides rigor, consistency, specificity, and prioritization to change management in a workload.
Reducing testing efforts to save time and the cost associated with test personnel, resources, and tooling can result in more bugs in production.
Delaying paying back technical debt to focus personnel efforts on new features can lead to slower development cycles and overall reduced agility.
Deprioritizing documentation to focus personnel efforts on product development can lead to longer onboarding time for new employees, impact the effectiveness of incident response, and compromise compliance requirements.
A lack of investment in training leads to stagnated skills, reducing the team's ability to adopt newer technologies and practices.
Removing automation tooling to save money can result in personnel spending more time on the tasks that are no longer automated. It also increases the risk of errors and inconsistencies.
Reducing planning efforts, like scoping and activity prioritization, to cut expenses can increase the likelihood of rework due to vague specifications and poor implementation.
Avoiding or reducing continuous improvement activities, like retrospectives and after-incident reports, to keep the workload team focused on delivery can create missed opportunities to optimize routine, unplanned, and emergency processes.
Tradeoff: Reduced observability.
Observability is necessary to help ensure that a workload has meaningful alerting and successful incident response.
Decreasing log and metric volume to save on storage and transfer costs reduces system observability and can lead to:
Fewer data points for creating alerts related to reliability, security, and performance.
Coverage gaps in incident response activities.
Limited observability into interactions or boundaries related to security or compliance.
Cost optimization design patterns can add components to a workload, increasing its complexity. The workload monitoring strategy must include those new components. For example, some patterns might introduce flows that span multiple components or shift processes from the server to the client. These changes can increase the complexity of correlating and tracking information.
Reduced investment in observability tooling and the maintenance of effective dashboards can decrease the ability to learn from production, validate design choices, and inform product design. This reduction can also hamper incident response activities and make it harder to meet the recovery time objective and SLO.
Tradeoff: Deferred maintenance.
Workload teams are expected to keep code, tooling, software packages, and operating systems patched and up to date in a timely and orderly way.
Letting maintenance contracts with tooling vendors expire can result in missed optimization features, bug resolutions, and security updates.
Increasing the time between system patches to save time can lead to missed bug fixes or a lack of protection against evolving security threats.
Cost Optimization tradeoffs with Performance Efficiency
The Cost Optimization and Performance Efficiency pillars both prioritize maximizing a workload's value. Performance Efficiency emphasizes meeting performance targets without spending more than necessary. Cost Optimization emphasizes maximizing the value produced by a workload's resources without exceeding performance targets. As a result, Cost Optimization often improves Performance Efficiency. However, there are Performance Efficiency tradeoffs associated with Cost Optimization. These tradeoffs can make it harder to reach performance targets and hinder ongoing performance optimization.
Tradeoff: Underprovisioned or underscaled resources.
A performance-efficient workload has enough resources to serve demand but doesn't have excessive unused overhead, even when usage patterns fluctuate.
Reducing costs by downsizing resources can deprive applications of resources. The application might not be able to handle significant usage pattern fluctuations.
Limiting or delaying scaling to cap or reduce costs might result in insufficient supply to meet demand.
Autoscale settings that scale down aggressively to reduce costs might leave a service unprepared for sudden spikes in demand or cause frequent scaling fluctuations (flapping).
Tradeoff: Lack of optimization over time.
Evaluating the effects of changes in functionality, changes in usage patterns, new technologies, and different approaches on the workload is one way to try to increase efficiency.
Limiting the focus on developing expertise in performance optimization in order to prioritize delivery can cause missed opportunities for improving resource usage efficiency.
Removing access performance testing or monitoring tools increases the risk of undetected performance issues. It also limits the ability for a workload team to execute on measure/improve cycles.
Neglecting areas prone to performance degradation, like data stores, can gradually deteriorate query performance and elevate overall system usage.
Related links
Explore the tradeoffs for the other pillars:
Reliability tradeoffs
Security tradeoffs
Operational Excellence tradeoffs
Performance Efficiency tradeoffs
Feedback
Was this page helpful?
Yes
No
No
Need help with this topic?
Want to try using Ask Learn to clarify or guide you through this topic?
Ask Learn
Ask Learn
Suggest a fix?
Additional resources
Last updated on
2026-04-27
