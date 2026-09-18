# GCP 공식 비용 최적화 가이드

- 출처: GCP 공식 문서 (Well-Architected Framework, 인증 불필요)
- 스냅샷 생성일: 2026-09-17
- 이 문서는 scripts/fetch_cost_optimization_guides.py가 아래 공식 URL에서 자동으로 가져온 스냅샷이다. 최신 내용은 원본 링크를 참고하라.

## 전체 (Well-Architected Framework — Cost Optimization Pillar, 단일 페이지)
(출처: https://docs.cloud.google.com/architecture/framework/cost-optimization/printable)

Home
Documentation
Cloud Architecture Center
Send feedback
Well-Architected Framework: Cost optimization pillar
Stay organized with collections
Save and categorize content based on your preferences.
Last reviewed 2025-02-14 UTC
This page provides a one-page view of all of the pages in the cost optimization pillar of the
Well-Architected Framework
.
You can print this page or save it in PDF format by using your browser's print
function.
This page doesn't have a table of contents. You can't use the links on this
page to navigate
within
the page.
The cost optimization pillar in the
Google Cloud Well-Architected Framework
describes principles and recommendations to optimize the cost of your workloads
in Google Cloud.
The intended audience includes the following:
CTOs, CIOs, CFOs, and other executives who are responsible for strategic
cost management.
Architects, developers, administrators, and operators who make decisions
that affect cost at all the stages of an organization's cloud journey.
The cost models for on-premises and cloud workloads differ significantly.
On-premises IT costs include capital expenditure (CapEx) and operational
expenditure (OpEx). On-premises hardware and software assets are acquired and
the acquisition costs are
depreciated
over the operating life of the assets. In the cloud, the costs for most cloud
resources are treated as OpEx, where costs are incurred when the cloud resources
are consumed. This fundamental difference underscores the importance of the
following core principles of cost optimization.
Note:
You might be able to classify the cost of some Google Cloud services (like
Compute Engine sole-tenant nodes) as capital expenditure. For more
information, see
Sole-tenancy accounting FAQ
.
For cost optimization principles and recommendations that are specific to AI and ML workloads, see
AI and ML perspective: Cost optimization
in the Well-Architected Framework.
Core principles
The recommendations in the cost optimization pillar of the Well-Architected Framework
are mapped to the following core principles:
Align cloud spending with business
value
:
Ensure that your cloud resources deliver measurable business value by
aligning IT spending with business objectives.
Foster a culture of cost
awareness
:
Ensure that people across your organization consider the cost impact of
their decisions and activities, and ensure that they have access to the cost
information required to make informed decisions.
Optimize resource
usage
:
Provision only the resources that you need, and pay only for the resources
that you consume.
Optimize
continuously
:
Continuously monitor your cloud resource usage and costs, and proactively
make adjustments as needed to optimize your spending. This approach involves
identifying and addressing potential cost inefficiencies before they become
significant problems.
These principles are closely aligned with the core tenets of
cloud FinOps
.
FinOps is relevant to any organization, regardless of its size or maturity in
the cloud. By adopting these principles and following the related
recommendations, you can control and optimize costs throughout your journey in
the cloud.
Contributors
Author:
Nicolas Pintaux
| Customer Engineer, Application Modernization Specialist
Other contributors:
Anuradha Bajpai
| Solutions Architect
Daniel Lees
| Cloud Security Architect
Eric Lam
| Head of Google Cloud FinOps
Fernando Rubbo
| Cloud Solutions Architect
Filipe Gracio, PhD
| Customer Engineer, AI/ML Specialist
Gary Harmson
| Principal Architect
Jose Andrade
| Customer Engineer, SRE Specialist
Kent Hua
| Solutions Manager
Kumar Dhanagopal
| Cross-Product Solution Developer
Marwan Al Shawi
| Partner Customer Engineer
Radhika Kanakam
| Program Lead, Google Cloud Well-Architected Framework
Samantha He
| Technical Writer
Steve McGhee
| Reliability Advocate
Sergei Lilichenko
| Solutions Architect
Wade Holmes
| Global Solutions Director
Zach Seils
| Networking Specialist
Align cloud spending with business value
This principle in the cost optimization pillar of the
Google Cloud Well-Architected Framework
provides recommendations to align your use of Google Cloud resources with
your organization's business goals.
Principle overview
To effectively manage cloud costs, you need to maximize the business value that
the cloud resources provide and minimize the
total cost of ownership (TCO)
.
When you evaluate the resource options for your cloud
workloads, consider not only the cost of provisioning and using the resources,
but also the cost of managing them. For example, virtual machines (VMs) on
Compute Engine
might be a cost-effective option for hosting applications.
However, when you consider the overhead to maintain, patch, and scale the VMs,
the TCO can increase. On the other hand, serverless services like
Cloud Run
can offer greater
business value. The lower operational overhead lets your team focus on core
activities and helps to increase agility.
To ensure that your cloud resources deliver optimal value, evaluate the following
factors:
Provisioning and usage costs
: The expenses incurred when you purchase,
provision, or consume resources.
Management costs
: The recurring expenses for operating and maintaining
resources, including tasks like patching, monitoring and scaling.
Indirect costs
: The costs that you might incur to manage issues like
downtime, data loss, or security breaches.
Business impact
: The potential benefits from the resources, like
increased revenue, improved customer satisfaction, and faster time to market.
By aligning cloud spending with business value, you get the following benefits:
Value-driven decisions
: Your teams are encouraged to prioritize solutions
that deliver the greatest business value and to consider both short-term and
long-term cost implications.
Informed resource choice
: Your teams have the information and knowledge
that they need to assess the business value and TCO of various deployment
options, so they choose resources that are cost-effective.
Cross-team alignment
: Cross-functional collaboration between business,
finance, and technical teams ensures that cloud decisions are aligned with
the overall objectives of the organization.
Recommendations
To align cloud spending with business objectives, consider the following recommendations.
Prioritize managed services and serverless products
Whenever possible, choose managed services and
serverless products
to reduce operational overhead and maintenance costs. This choice lets your teams
concentrate on their core business activities. They can accelerate the delivery
of new features and functionalities, and help drive innovation and value.
The following are examples of how you can implement this recommendation:
To run PostgreSQL, MySQL, or Microsoft SQL Server server databases, use
Cloud SQL
instead of deploying those databases on VMs.
To run and manage Kubernetes clusters, use
Google Kubernetes Engine (GKE) Autopilot
instead of deploying containers on VMs.
For your Apache Hadoop or Apache Spark processing needs, use
Managed Service for Apache Spark
and
Managed Service for Apache Spark Serverless
.
Per-second billing can help to achieve significantly
lower TCO
when compared to on-premises data lakes.
Balance cost efficiency with business agility
Controlling costs and optimizing resource utilization are important goals.
However, you must balance these goals with the need for flexible infrastructure
that lets you innovate rapidly, respond quickly to changes, and deliver value
faster. The following are examples of how you can achieve this balance:
Adopt
DORA metrics
for software delivery performance. Metrics like change failure rate (CFR),
time to detect (TTD), and time to restore (TTR) can help to identify and fix
bottlenecks in your development and deployment processes. By reducing downtime
and accelerating delivery, you can achieve both operational efficiency and
business agility.
Follow
Site Reliability Engineering (SRE)
practices to improve operational reliability. SRE's focus on automation,
observability, and incident response can lead to reduced downtime, lower
recovery time, and higher customer satisfaction. By minimizing downtime and
improving operational reliability, you can prevent revenue loss and avoid
the need to overprovision resources as a safety net to handle outages.
Enable self-service optimization
Encourage a culture of experimentation and exploration by providing your teams
with self-service cost optimization tools, observability tools, and resource
management platforms. Enable them to provision, manage, and optimize their cloud
resources autonomously. This approach helps to foster a sense of ownership,
accelerate innovation, and ensure that teams can respond quickly to changing needs
while being mindful of cost efficiency.
Adopt and implement FinOps
Adopt FinOps to establish a collaborative environment where everyone is empowered
to make informed decisions that balance cost and value. FinOps fosters financial
accountability and promotes effective cost optimization in the cloud.
Promote a value-driven and TCO-aware mindset
Encourage your team members to adopt a holistic attitude toward cloud spending,
with an emphasis on TCO and not just upfront costs. Use techniques like
value stream mapping
to visualize and analyze the flow of value through your software delivery process
and to identify areas for improvement.
Gain a granular understanding of cost drivers by using unit costing for your
applications and services. Adopt
unit economics
to balance costs against revenue or business metrics. By correlating cloud
spending with business units of measure, such as revenue per customer or
transaction volume, you can measure unit margins and verify that increasing
spend is driven by profitable growth. When you balance cost against revenue,
your organization can distinguish between operational inefficiency and healthy
scaling. This helps you identify when further cloud investments are justified. For
more information, see
Maximize business value with cloud FinOps
.
Foster a culture of cost awareness
This principle in the cost optimization pillar of the
Google Cloud Well-Architected Framework
provides recommendations to promote cost awareness across your organization and
ensure that team members have the cost information that they need to make
informed decisions.
Conventionally, the responsibility for cost management might be centralized to a
few select stakeholders and primarily focused on initial project architecture
decisions. However, team members across all cloud user roles (analyst, architect,
developer, or administrator) can help to reduce the cost of your resources in
Google Cloud. By sharing cost data appropriately, you can empower team
members to make cost-effective decisions throughout their development and
deployment processes.
Principle overview
Stakeholders across various roles – product owners, developers, deployment
engineers, administrators, and financial analysts – need visibility into relevant
cost data and its relationship to business value. When provisioning and managing
cloud resources, they need the following data:
Projected resource costs
: Cost estimates at the time of design and
deployment.
Real-time resource usage costs
: Up-to-date cost data that can be used for
ongoing monitoring and budget validation.
Costs mapped to business metrics
: Insights into how cloud spending affects
key performance indicators (KPIs), to enable teams to identify cost-effective
strategies.
Every individual might not need access to raw cost data. However, promoting cost
awareness across all roles is crucial because individual decisions can affect
costs.
By promoting cost visibility and ensuring clear ownership of cost management
practices, you ensure that everyone is aware of the financial implications of
their choices and everyone actively contributes to the organization's cost
optimization goals. Whether through a centralized FinOps team or a distributed
model, establishing accountability is crucial for effective cost optimization
efforts.
Recommendations
To promote cost awareness and ensure that your team members have the cost
information that they need to make informed decisions, consider the following
recommendations.
Provide organization-wide cost visibility
To achieve organization-wide cost visibility, the teams that are responsible for
cost management can take the following actions:
Standardize cost calculation and budgeting
: Use a consistent method to
determine the full costs of cloud resources, after factoring in discounts and
shared costs. Establish clear and standardized budgeting processes that align
with your organization's goals and enable proactive cost management.
Use standardized cost management and visibility tools
: Use appropriate
tools that provide real-time insights into cloud spending and generate
regular (for example, weekly) cost progression snapshots. These tools enable
proactive budgeting, forecasting, and identification of optimization
opportunities. The tools could be cloud provider tools
(like the
Google Cloud Billing dashboard
),
third-party solutions, or open-source solutions like the
Cost Attribution solution
.
Implement a cost allocation system
: Allocate a portion of the overall
cloud budget to each team or project. Such an allocation gives the teams a
sense of ownership over cloud spending and encourages them to make
cost-effective decisions within their allocated budget.
Promote transparency
: Encourage teams to discuss cost implications during
the design and decision-making processes. Create a safe and supportive
environment for sharing ideas and concerns related to cost optimization.
Some organizations use positive reinforcement mechanisms like leaderboards
or recognition programs. If your organization has restrictions on sharing
raw cost data due to business concerns, explore alternative approaches for
sharing cost information and insights. For example, consider sharing
aggregated metrics (like the total cost for an environment or feature) or
relative metrics (like the average cost per transaction or user).
Understand how cloud resources are billed
Pricing for Google Cloud resources might vary across
regions
.
Some resources are billed monthly at a fixed price, and others might be billed
based on usage.
To understand how Google Cloud resources are billed, use the
Google Cloud pricing calculator
and product-specific pricing information (for example,
Google Kubernetes Engine (GKE) pricing
).
Understand resource-based cost optimization options
For each type of cloud resource that you plan to use, explore strategies to
optimize utilization and efficiency. The strategies include rightsizing,
autoscaling, and adopting serverless technologies where appropriate. The following
are examples of cost optimization options for a few Google Cloud products:
Cloud Run lets you configure
always-allocated CPUs
to handle predictable traffic loads at a fraction of the price of the default
allocation method (that is, CPUs allocated only during request processing).
You can purchase
BigQuery slot commitments
to save money on data analysis.
GKE
provides detailed metrics to help you understand cost optimization options.
Understand how
network pricing
can affect the cost of data transfers and how you can optimize costs for
specific networking services. For example, you can reduce the data transfer
costs for external Application Load Balancers by using Cloud CDN or Google Cloud Armor.
For more information, see
Ways to lower external Application Load Balancer costs
.
Understand discount-based cost optimization options
Familiarize yourself with the discount programs that Google Cloud offers,
such as the following examples:
Committed use discounts (CUDs)
:
CUDs are suitable for resources that have predictable and steady usage. CUDs
let you get significant reductions in price in exchange for committing to
specific resource usage over a period (typically one to three years). You
can also use
CUD auto-renewal
to avoid having to manually repurchase commitments when they expire.
Sustained use discounts
:
For certain Google Cloud products like Compute Engine and
GKE, you can get automatic discount credits after
continuous resource usage beyond specific duration thresholds.
Spot VMs
:
For fault-tolerant and flexible workloads, Spot VMs can help to
reduce your Compute Engine costs. The cost of Spot VMs is
significantly lower than regular VMs. However, Compute Engine might
preemptively stop or delete Spot VMs to reclaim capacity.
Spot VMs are suitable for batch jobs that can tolerate preemption
and don't have high availability requirements.
Discounts for specific product options
: Some managed services like
BigQuery offer
discounts
when you purchase dedicated or autoscaling query processing capacity.
Evaluate and choose the discounts options that align with your workload
characteristics and usage patterns.
Incorporate cost estimates into architecture blueprints
Encourage teams to develop architecture blueprints that include cost estimates
for different deployment options and configurations. This practice empowers teams
to compare costs proactively and make informed decisions that align with both
technical and financial objectives.
Use a consistent and standard set of labels for all your resources
You can use
labels
to track costs and to identify and classify resources. Specifically, you can use
labels to allocate costs to different projects, departments, or cost centers.
Defining a
formal labeling policy
that aligns with the needs of the main stakeholders in your organization helps
to make costs visible more widely. You can also use labels to filter resource
cost and usage data based on target audience.
Use automation tools like Terraform to enforce labeling on every resource that
is created. To enhance cost visibility and attribution further, you can use the
tools provided by the open-source
cost attribution solution
.
Share cost reports with team members
By sharing cost reports with your team members, you empower them to take
ownership of their cloud spending. This practice enables cost-effective decision
making, continuous cost optimization, and systematic improvements to your cost
allocation model.
Cost reports can be of several types, including the following:
Periodic cost reports
: Regular reports inform teams about their current
cloud spending. Conventionally, these reports might be spreadsheet exports.
More effective methods include automated emails and specialized dashboards.
To ensure that cost reports provide relevant and actionable information
without overwhelming recipients with unnecessary detail, the reports must
be tailored to the target audiences. Setting up tailored reports is a
foundational step toward more real-time and interactive cost visibility and
management.
Automated notifications
: You can configure cost reports to proactively
notify relevant stakeholders (for example, through email or chat) about cost
anomalies, budget thresholds, or opportunities for cost optimization. By
providing timely information directly to those who can act on it, automated
alerts encourage prompt action and foster a proactive approach to cost
optimization.
Google Cloud dashboards
: You can use the
built-in billing dashboards
in Google Cloud to get insights into cost breakdowns and to identify
opportunities for cost optimization. Google Cloud also provides
FinOps hub
to help you monitor savings and get recommendations for cost optimization.
An AI engine powers the FinOps hub to recommend cost optimization
opportunities for all the resources that are currently deployed. To control
access to these recommendations, you can implement role-based access control
(RBAC).
Custom dashboards
: You can create custom dashboards by exporting cost
data to an analytics database, like
BigQuery
.
Use a visualization tool like
Data Studio
to connect to the analytics database to build interactive reports and enable
fine-grained access control through role-based permissions.
Multicloud cost reports
: For multicloud deployments, you need a
unified view of costs across all the cloud providers to ensure comprehensive
analysis, budgeting, and optimization. Use tools like BigQuery
to centralize and analyze cost data from multiple cloud providers, and use
Data Studio to build team-specific interactive reports.
Optimize resource usage
This principle in the cost optimization pillar of the
Google Cloud Well-Architected Framework
provides recommendations to help you plan and provision resources to match the requirements
and consumption patterns of your cloud workloads.
Principle overview
To optimize the cost of your cloud resources, you need to thoroughly understand
your workloads resource requirements and load patterns. This understanding is
the basis for a well defined cost model that lets you forecast the total cost of
ownership (TCO) and identify cost drivers throughout your cloud adoption journey.
By proactively analyzing and forecasting cloud spending, you can make informed
choices about resource provisioning, utilization, and cost optimization. This
approach lets you control cloud spending, avoid overprovisioning, and ensure that
cloud resources are aligned with the dynamic needs of your workloads and
environments.
Recommendations
To effectively optimize cloud resource usage, consider the following recommendations.
Choose environment-specific resources
Each deployment environment has different requirements for availability,
reliability and scalability. For example, developers might prefer an environment
that lets them rapidly deploy and run applications for short durations, but might
not need high availability. On the other hand, a production environment typically
needs high availability. To maximize the utilization of your resources, define
environment-specific requirements based on your business needs. The following
table lists examples of environment-specific requirements.
Note:
The requirements that are listed in this table are not exhaustive or
prescriptive. They're meant to serve as examples to help you understand how
requirements can vary based on the environment type.
Environment
Requirements
Production
High availability
Predictable performance
Operational stability
Security with robust resources
Development and testing
Cost efficiency
Flexible infrastructure with
burstable capacity
Ephemeral infrastructure when data persistence is not necessary
Other environments (like staging and QA)
Tailored resource allocation based on environment-specific requirements
Choose workload-specific resources
Each of your cloud workloads might have different requirements for availability,
scalability, security, and performance. To optimize costs, you need to align
resource choices with the specific requirements of each workload. For example,
a stateless application might not require the same level of availability or
reliability as a stateful backend. The following table lists more examples of
workload-specific requirements.
Note:
The requirements that are listed in this table are not exhaustive or
prescriptive. They're meant to serve as examples to help you understand how
requirements can vary based on the workload type.
Workload type
Workload requirements
Resource options
Mission-critical
Continuous availability, robust security, and high performance
Premium resources and managed services like
Spanner
for high availability and global consistency of data.
Non-critical
Cost-efficient and autoscaling infrastructure
Resources with basic features and ephemeral resources like
Spot VMs
.
Event-driven
Dynamic scaling based on the current demand for capacity and performance
Serverless services like
Cloud Run
and
Cloud Run functions
.
Experimental workloads
Low cost and flexible environment for rapid development, iteration, testing,
and innovation
Resources with basic features, ephemeral resources like
Spot VMs
, and
sandbox environments with defined spending limits.
A benefit of the cloud is the opportunity to take advantage of the most
appropriate computing power for a given workload. Some workloads are developed
to take advantage of processor instruction sets, and others might not be designed
in this way. Benchmark and profile your workloads accordingly. Categorize your
workloads and make workload-specific resource choices (for example, choose
appropriate
machine families
for Compute Engine VMs). This practice helps
to optimize costs, enable innovation, and maintain the level of availability and
performance that your workloads need.
The following are examples of how you can implement this recommendation:
For mission-critical workloads that serve globally distributed users, consider
using
Spanner
. Spanner removes the need for complex database deployments by
ensuring reliability and consistency of data in all
regions
.
For workloads with fluctuating load levels, use autoscaling to ensure that
you don't incur costs when the load is low and yet maintain sufficient
capacity to meet the current load. You can configure autoscaling for many
Google Cloud services, including
Compute Engine VMs
,
Google Kubernetes Engine (GKE) clusters
,
and
Cloud Run
. When you set up
autoscaling, you can configure maximum scaling limits to ensure that costs
remain within specified budgets.
Select regions based on cost requirements
For your cloud workloads, carefully evaluate the available Google Cloud
regions and choose regions that align with your cost objectives. The region with
lowest cost might not offer optimal latency or it might not meet your
sustainability requirements. Make informed decisions about where to deploy your
workloads to achieve the desired balance. You can use the
Google Cloud Region Picker
to understand the trade-offs between cost, sustainability, latency, and other
factors.
Use built-in cost optimization options
Google Cloud products provide built-in features to help you optimize
resource usage and control costs. The following table lists examples of cost
optimization features that you can use in some Google Cloud products:
Product
Cost optimization feature
Compute Engine
Automatically add or remove VMs based on the current load by using
autoscaling
.
Avoid overprovisioning by creating and using
custom machine types
that match your workload's requirements.
For non-critical or fault-tolerant workloads, reduce costs by using
Spot VMs
.
In development environments, reduce costs by
limiting the run time
of
VMs or by
suspending
or
stopping
VMs when
you don't need them.
GKE
Automatically adjust the size of GKE clusters based on the current load
by using
cluster
autoscaler
.
Automatically create and manage node pools based on workload requirements
and ensure optimal resource utilization by using
node auto-provisioning
.
Cloud Storage
Automatically transition data to lower-cost storage classes based on the age
of data or based on access patterns by using
Object Lifecycle Management
.
Dynamically move data to the most cost-effective storage class based on usage
patterns by using
Autoclass
.
BigQuery
Reduce query processing costs for steady-state workloads by using
capacity-based pricing.
Optimize query performance and costs by using partitioning and clustering techniques.
Google Cloud VMware Engine
Reduce VMware costs by using
cost-optimization strategies
like  CUDs, optimizing storage
consumption, and rightsizing ESXi clusters.
Optimize resource sharing
To maximize the utilization of cloud resources, you can deploy multiple
applications or services on the same infrastructure, while still meeting the
security and other requirements of the applications. For example, in development
and testing environments, you can use the same cloud infrastructure to test all
the components of an application. For the production environment, you can deploy
each component on a separate set of resources to limit the extent of impact in
case of incidents.
The following are examples of how you can implement this recommendation:
Use a single
Cloud SQL
instance for multiple non-production environments.
Enable multiple development teams to share a GKE cluster by using the
fleet team management
feature in GKE
with appropriate access controls.
Use
GKE Autopilot
to take advantage of
cost-optimization techniques like bin packing and autoscaling that
GKE implements by default.
For AI and ML workloads, save GPU costs by using
GPU-sharing strategies
like multi-instance GPUs, time-sharing GPUs, and NVIDIA MPS.
Develop and maintain reference architectures
Create and maintain a repository of reference architectures that are tailored to
meet the requirements of different deployment environments and workload types.
To streamline the design and implementation process for individual projects, the
blueprints can be centrally managed by a team like a
Cloud Center of Excellence
(CCoE). Project teams
can choose suitable blueprints based on clearly defined criteria, to ensure
architectural consistency and adoption of best practices. For requirements that
are unique to a project, the project team and the central architecture team should
collaborate to design new reference architectures. You can share the reference
architectures across the organization to foster knowledge sharing and expand the
repository of available solutions. This approach ensures consistency, accelerates
development, simplifies decision-making, and promotes efficient resource
utilization.
Review the
reference architectures
provided by Google for various use cases and
technologies. These reference architectures incorporate best practices for
resource selection, sizing, configuration, and deployment. By using these
reference architectures, you can accelerate your development process and achieve
cost savings from the start.
Enforce cost discipline by using organization policies
Consider using
organization policies
to limit the available Google Cloud locations and products that team
members can use. These policies help to ensure that teams adhere to cost-effective
solutions and provision resources in locations that are aligned with your cost
optimization goals.
Estimate realistic budgets and set financial boundaries
Develop detailed budgets for each project, workload, and deployment environment.
Make sure that the budgets cover all aspects of cloud operations, including
infrastructure costs, software licenses, personnel, and anticipated growth. To
prevent overspending and ensure alignment with your financial goals, establish
clear spending limits or thresholds for projects, services, or specific resources.
Monitor cloud spending regularly against these limits. You can use
proactive quota alerts
to identify potential cost overruns early and take timely corrective action.
In addition to setting budgets, you can use
quotas
and limits to help enforce cost discipline and
prevent unexpected spikes in spending. You can exercise granular control over
resource consumption by setting quotas at various levels, including projects,
services, and even specific resource types.
The following are examples of how you can implement this recommendation:
Project-level quotas
: Set spending limits or resource quotas at the
project level to establish overall financial boundaries and control resource
consumption across all the services within the project.
Service-specific quotas
: Configure quotas for specific Google Cloud
services like Compute Engine or BigQuery to limit the
number of instances, CPUs, or storage capacity that can be provisioned.
Resource type-specific quotas
: Apply quotas to individual resource types
like Compute Engine VMs, Cloud Storage buckets,
Cloud Run instances, or GKE nodes to
restrict their usage and prevent unexpected cost overruns.
Quota alerts
: Get notifications when your quota usage (at the project
level) reaches a percentage of the maximum value.
By using quotas and limits in conjunction with budgeting and monitoring, you can
create a proactive and multi-layered approach to cost control. This approach
helps to ensure that your cloud spending remains within defined boundaries and
aligns with your business objectives. Remember, these cost controls are not
permanent or rigid. To ensure that the cost controls remain aligned with current
industry standards and reflect your evolving business needs, you must review the
controls regularly and adjust them to include new technologies and best practices.
Optimize continuously
This principle in the cost optimization pillar of the
Google Cloud Well-Architected Framework
provides recommendations to help you optimize the cost of your cloud deployments
based on constantly changing and evolving business goals.
As your business grows and evolves, your cloud workloads need to adapt to changes
in resource requirements and usage patterns. To derive maximum value from your
cloud spending, you must maintain cost-efficiency while continuing to support
business objectives. This requires a proactive and adaptive approach that focuses
on continuous improvement and optimization.
Principle overview
To optimize cost continuously, you must proactively monitor and analyze your
cloud environment and make suitable adjustments to meet current requirements.
Focus your monitoring efforts on key performance indicators (KPIs) that directly
affect your end users' experience, align with your business goals, and provide
insights for continuous improvement. This approach lets you identify and address
inefficiencies, adapt to changing needs, and continuously align cloud spending
with strategic business goals. To balance comprehensive observability with cost
effectiveness, understand the costs and benefits of monitoring resource usage
and use appropriate process-improvement and optimization strategies.
Recommendations
To effectively monitor your Google Cloud environment and optimize cost
continuously, consider the following recommendations.
Focus on business-relevant metrics
Effective monitoring starts with identifying the metrics that are most important
for your business and customers. These metrics include the following:
User experience metrics
: Latency, error rates, throughput, and customer
satisfaction metrics are useful for understanding your end users' experience
when using your applications.
Business outcome metrics
: Revenue, customer growth, and engagement can
be correlated with resource usage to identify opportunities for cost
optimization.
DevOps Research & Assessment (DORA)
metrics
: Metrics
like deployment frequency, lead time for changes, change failure rate, and
time to restore provide insights into the efficiency and reliability of your
software delivery process. By improving these metrics, you can increase
productivity, reduce downtime, and optimize cost.
Site Reliability Engineering (SRE)
metrics
: Error
budgets help teams to quantify and manage the acceptable level of service
disruption. By establishing clear expectations for reliability, error budgets
empower teams to innovate and deploy changes more confidently, knowing their
safety margin. This proactive approach promotes a balance between innovation
and stability, helping prevent excessive operational costs associated with
major outages or prolonged downtime.
Use observability for resource optimization
The following are recommendations to use observability to identify resource
bottlenecks and underutilized resources in your cloud deployments:
Monitor resource utilization
: Use resource utilization metrics to identify
Google Cloud resources that are underutilized. For example, use metrics
like CPU and memory utilization to identify
idle VM resources
.
For Google Kubernetes Engine (GKE), you can view a detailed
breakdown of costs
and
cost-related optimization metrics
.
For Google Cloud VMware Engine,
review resource utilization
to optimize CUDs, storage consumption, and ESXi right-sizing.
Use cloud recommendations
:
Active Assist
is a portfolio of intelligent tools that help you optimize your cloud
operations. These tools provide actionable recommendations to reduce costs,
increase performance, improve security and even make sustainability-focused
decisions. For example,
VM rightsizing insights
can help to optimize resource allocation and avoid unnecessary spending.
Correlate resource utilization with performance
: Analyze the relationship
between resource utilization and application performance to determine whether
you can downgrade to less expensive resources without affecting the user
experience.
Balance troubleshooting needs with cost
Detailed observability data can help with diagnosing and troubleshooting issues.
However, storing excessive amounts of observability data or exporting unnecessary
data to external monitoring tools can lead to unnecessary costs. For efficient
troubleshooting, consider the following recommendations:
Collect sufficient data for troubleshooting
: Ensure that your monitoring
solution captures enough data to efficiently diagnose and resolve issues when
they arise. This data might include logs, traces, and metrics at various
levels of granularity.
Use sampling and aggregation
: Balance the need for detailed data with
cost considerations by using sampling and aggregation techniques. This approach
lets you collect representative data without incurring excessive storage costs.
Understand the pricing models of your monitoring tools and services
: Evaluate
different monitoring solutions and choose options that align with your
project's specific needs, budget, and usage patterns. Consider factors like
data volume, retention requirements, and the required features when
making your selection.
Regularly review your monitoring configuration
: Avoid collecting excessive
data by removing unnecessary metrics or logs.
Tailor data collection to roles and set role-specific retention policies
Consider the specific data needs of different roles. For example, developers
might primarily need access to traces and application-level logs, whereas IT
administrators might focus on system logs and infrastructure metrics. By tailoring
data collection, you can reduce unnecessary storage costs and avoid overwhelming
users with irrelevant information.
Additionally, you can define retention policies based on the needs of each role
and any regulatory requirements. For example, developers might need access to
detailed logs for a shorter period, while financial analysts might require
longer-term data.
Consider regulatory and compliance requirements
In certain industries, regulatory requirements mandate data retention. To avoid
legal and financial risks, you need to ensure that your monitoring and data
retention practices help you adhere to relevant regulations. At the same time,
you need to maintain cost efficiency. Consider the following recommendations:
Determine the specific data retention requirements for your industry or region,
and ensure that your monitoring strategy meets the requirements of those
requirements.
Implement appropriate data archival and retrieval mechanisms to meet audit
and compliance needs while minimizing storage costs.
Implement smart alerting
Alerting helps to detect and resolve issues in a timely manner. However, a
balance is necessary between an approach that keeps you informed, and one that
overwhelms you with notifications. By designing intelligent alerting systems,
you can prioritize critical issues that have higher business impact. Consider
the following recommendations:
Prioritize issues that affect customers
: Design alerts that trigger
rapidly for issues that directly affect the customer experience, like website
outages, slow response times, or transaction failures.
Tune for temporary problems
: Use appropriate thresholds and delay
mechanisms to avoid unnecessary alerts for temporary problems or self-healing
system issues that don't affect customers.
Customize alert severity
: Ensure that the most urgent issues receive
immediate attention by differentiating between critical and noncritical
alerts.
Use notification channels wisely
: Choose appropriate channels for alert
notifications (email, SMS, or paging) based on the severity and urgency of
the alerts.
Send feedback
Except as otherwise noted, the content of this page is licensed under the
Creative Commons Attribution 4.0 License
, and code samples are licensed under the
Apache 2.0 License
. For details, see the
Google Developers Site Policies
. Java is a registered trademark of Oracle and/or its affiliates.
Last updated 2025-02-14 UTC.
