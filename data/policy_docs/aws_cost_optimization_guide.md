# AWS 공식 비용 최적화 가이드

- 출처: AWS 공식 문서 (Well-Architected Framework, 인증 불필요)
- 스냅샷 생성일: 2026-09-17
- 이 문서는 scripts/fetch_cost_optimization_guides.py가 아래 공식 URL에서 자동으로 가져온 스냅샷이다. 최신 내용은 원본 링크를 참고하라.

## 개요
(출처: https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html)

Cost Optimization Pillar - AWS Well-Architected Framework
Publication date:
June 27, 2024
(
Document revisions
)
Abstract
This whitepaper focuses on the cost optimization pillar of the
Amazon Web Services (AWS) Well-Architected Framework. It provides
guidance to help customers apply best practices in the design,
delivery, and maintenance of AWS environments.
A cost-optimized workload fully utilizes all resources, achieves an
outcome at the lowest possible price point, and meets your
functional requirements. This whitepaper provides in-depth guidance
for building capability within your organization, designing your
workload, selecting your services, configuring and operating the
services, and applying cost optimization techniques.
Introduction
The
AWS
Well-Architected Framework
helps you understand the decisions
you make while building workloads on AWS. The Framework provides
architectural best practices for designing and operating reliable,
secure, efficient, cost-effective, and sustainable workloads in the cloud. It
demonstrates a way to consistently measure your architectures
against best practices and identify areas for improvement. We
believe that having well-architected workloads greatly increases the
likelihood of business success.
The framework is based on six pillars:
Operational Excellence
Security
Reliability
Performance Efficiency
Cost Optimization
Sustainability
This paper focuses on the cost optimization pillar, and how to
architect workloads with the most effective use of services and
resources, to achieve business outcomes at the lowest price point.
Youâll learn how to apply the best practices of the cost
optimization pillar within your organization. Cost optimization can
be challenging in traditional on-premises solutions because you must
predict future capacity and business needs while navigating complex
procurement processes. Adopting the practices in this paper will
help your organization achieve the following goals:
Practice Cloud Financial Management
Expenditure and usage awareness
Cost effective resources
Manage demand and supply resources
Optimize over time
This paper is intended for those in technology and finance roles,
such as chief technology officers (CTOs), chief financial officers
(CFOs), architects, developers, financial controllers, financial
planners, business analysts, and operations team members. This paper
does not provide implementation details or architectural patterns,
however, it does include references to appropriate resources.
Javascript is disabled or is unavailable in your browser.
To use the Amazon Web Services Documentation, Javascript must be enabled. Please refer to your browser's Help pages for instructions.
Document Conventions
Cost optimization

## 클라우드 재무 관리 실천
(출처: https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/practice-cloud-financial-management.html)

Practice Cloud Financial Management
Managing cloud finance requires evolving your existing finance processes to establish and operate with cost transparency,
control, planning, and optimization for your AWS environments.
Applying traditional, static waterfall planning, IT budgeting, and cost assessment models to dynamic cloud usage can create risks,
lead to inaccurate planning, and result in less visibility. Ultimately, this results in a lost opportunity to eï¬ectively optimize
and control costs and realize long-term business value. To avoid these pitfalls, actively manage costs throughout the cloud journey,
whether you are building applications natively in the cloud, migrating your workloads to the cloud, or expanding your adoption of
cloud services.
Cloud Financial Management
(CFM) allows finance, product, technology, and business organizations to manage, optimize,
and plan costs as they grow their usage and scale on AWS. The primary goal of CFM is to allow customers to achieve their
business outcomes in the most cost-efficient manner and accelerate economic and business value creation while finding the
right balance between agility and control.
CFM solutions help transform your business through cost transparency, control, forecasting,
and optimization. These solutions can also create a cost-conscious culture that drives
accountability across all teams and functions. Finance teams can see where costs are coming
from, run operations with minimal unexpected expenses, plan for dynamic cloud usage, and save on
cloud expenses while teams scale their adoptions in the cloud. Sharing this with engineering
teams can provide necessary financial context for their resource selection, use, and
optimization.
AWS CFM offers a set of capabilities to manage, optimize, and plan for cloud costs while maintaining business agility.
CFM is paramount not only to effectively manage costs, but also to verify that investments are driving expected business outcomes. These are the four
pillars of the Cloud Financial Management Framework in the AWS Cloud:
see
,
save
,
plan
, and
run
. Each of these pillars has a set of activities and
capabilities.
The four pillars of Cloud Financial Management.
See:
How are you currently measuring, monitoring and creating accountability for your cloud spend?
If you are new to AWS or planning on using AWS, do you have a plan to establish cost and usage visibility?
To understand your AWS costs and optimize spending, you need to know where those costs are coming from. This requires a deliberate
structure for your accounts and resources, helping your finance organization track spending flows and hold teams accountable
for their portion of the bottom line.
AWS Services:
AWS Control Tower, AWS Organizations, Cost allocations tags, Tag policies, AWS Resource Groups, AWS Cost Categories,
AWS Cost Explorer, AWS Cost and Usage Report, RIs and SPs
Resources:
AWS Tagging Best Practices, AWS Cost Categories
Save:
What cost optimization levers are you currently using to optimize your spend? If you are not
using AWS, are you familiar with common usage-based and pricing model-based optimizations?
In the save tenet, we optimize costs with pricing and resource recommendations. Optimizing costs begins with having a well-defined strategy
for your new cloud operating model. Ideally, this should start as early as possible in your cloud journey, setting the stage for a cost-conscious
culture reinforced by the right processes and behaviors.
There are many different ways you can optimize cloud costs. One of them is selecting the right purchase model (RIs and SPs) or whether your
workload is immutable and containerized so that you can adopt Amazon EC2 Spot Instances. In addition, scale your workload using Amazon EC2 Auto Scaling Groups.
AWS Services:
RIs and SPs, Amazon EC2 Auto Scaling Groups, Spot Instances
Resources:
Reserved Instances, Savings Plans, Best practices for handling Amazon EC2
Plan:
How do you currently plan for future cloud usage and spend? Do you have a methodology to
quantify value generation for a new migration?  Have you evolved your current budgeting and forecasting processes to adopt variable
usage of the cloud?
The plan tenet means improving your planning with flexible budgeting and forecasting. Once youâve established visibility and cost controls,
you will likely want to plan and set expectations for spending on cloud projects. AWS gives you the flexibility to build dynamic
forecasting and budgeting processes so you can stay informed on whether costs adhere to, or exceed, budgetary limits.
AWS Services:
AWS Cost Explorer, AWS Cost and Usage Report, AWS Budgets
Resources:
Usage-Based Forecasting, AWS Budget Reports and Alerts
Run:
What are some of the operational processes and tools you are currently using to manage your cloud
expenditures, and who is leading those efforts?   Have you put any thought into how things will work from a daily operations perspective
once you start using AWS?
The run tenet is actually managing billing and cost control. You can establish guardrails and set governance to ensure expenses stay in
line with budgets. AWS provides several tools to help you get started.
AWS Services:
AWS Billing and Cost Management Console, AWS Identity and Access Management, Service Control Policies (SCP), AWS Service Catalog, AWS Cost Anomaly Detection, AWS Budgets
Resources:
Getting Started with AWS Billing Console
The following are Cloud Financial Management best practices:
Best practices
COST01-BP01 Establish ownership of cost optimization
COST01-BP02 Establish a partnership between finance and technology
COST01-BP03 Establish cloud budgets and forecasts
COST01-BP04 Implement cost awareness in your organizational processes
COST01-BP05 Report and notify on cost optimization
COST01-BP06 Monitor cost proactively
COST01-BP07 Keep up-to-date with new service releases
COST01-BP08 Create a cost-aware culture
COST01-BP09 Quantify business value from cost optimization
Javascript is disabled or is unavailable in your browser.
To use the Amazon Web Services Documentation, Javascript must be enabled. Please refer to your browser's Help pages for instructions.
Document Conventions
Definition
COST01-BP01 Establish ownership of cost optimization

## 지출·사용 인지
(출처: https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/expenditure-and-usage-awareness.html)

Expenditure and usage awareness
Understanding your organizationâs costs and drivers is critical for
managing your cost and usage effectively, and identifying
cost-reduction opportunities. Organizations typically operate
multiple workloads run by multiple teams. These teams can be in
different organization units, each with its own revenue stream. The
capability to attribute resource costs to the workloads, individual
organization, or product owners drives efficient usage behavior and
helps reduce waste. Accurate cost and usage monitoring allows you to
understand how profitable organization units and products are, and
allows you to make more informed decisions about where to allocate
resources within your organization. Awareness of usage at all levels
in the organization is key to driving change, as change in usage
drives changes in cost.
Consider taking a multi-faceted approach to becoming aware of your
usage and expenditures. Your team must gather data, analyze, and
then report. Key factors to consider include:
Topics
Governance
Monitor cost and usage
Decommission resources
Javascript is disabled or is unavailable in your browser.
To use the Amazon Web Services Documentation, Javascript must be enabled. Please refer to your browser's Help pages for instructions.
Document Conventions
COST01-BP09 Quantify business value from cost optimization
Governance

## 비용 효율적 리소스
(출처: https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/cost-effective-resources.html)

Cost effective resources
Using the appropriate services, resources, and configurations for your workloads is key to
cost savings.Consider the following when creating cost-effective resources:
You can use AWS Solutions Architects, AWS Solutions, AWS Reference
Architectures, and APN Partners to help you choose an architecture based on what you have
learned.
Topics
Evaluate cost when selecting services
Select the correct resource type, size, and number
Select the best pricing model
Plan for data transfer
Javascript is disabled or is unavailable in your browser.
To use the Amazon Web Services Documentation, Javascript must be enabled. Please refer to your browser's Help pages for instructions.
Document Conventions
COST04-BP05 Enforce data retention policies
Evaluate cost when selecting services

## 수요·공급 관리
(출처: https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/manage-demand-and-supply-resources.html)

Manage demand and supply resources
When you move to the cloud, you pay only for what you need. You can
supply resources to match the workload demand at the time theyâre
needed â eliminating the need for costly and wasteful
overprovisioning. You can also modify the demand using a throttle,
buffer, or queue to smooth the demand and serve it with less
resources.
The economic benefits of just-in-time supply should be balanced
against the need to provision to account for resource failures, high
availability, and provision time. Depending on whether your demand
is fixed or variable, plan to create metrics and automation that
will ensure that management of your environment is minimal â even as
you scale. When modifying the demand, you must know the acceptable
and maximum delay that the workload can allow.
In AWS, you can use a number of different approaches for managing
demand and supplying resources. The following best practices describe how
to use these approaches.
Best practices
COST09-BP01 Perform an analysis on the workload demand
COST09-BP02 Implement a buffer or throttle to manage demand
COST09-BP03 Supply resources dynamically
Javascript is disabled or is unavailable in your browser.
To use the Amazon Web Services Documentation, Javascript must be enabled. Please refer to your browser's Help pages for instructions.
Document Conventions
COST08-BP03 Implement services to reduce data transfer
costs
COST09-BP01 Perform an analysis on the workload demand

## 지속적 최적화
(출처: https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/optimize-over-time.html)

Optimize over time
In AWS, you optimize over time by reviewing new services and implementing them in your
workload.
As AWS releases new services and features, it is a best practice to review your existing
architectural decisions to ensure that they remain cost effective. As your requirements change,
be aggressive in decommissioning resources, components, and workloads that you no longer
require. Consider the following best practices to help you optimize over time.
While optimizing your workloads over time and improving your
CFM
culture in your organization,
evaluate the cost of effort for operations in the cloud, review your time-consuming cloud operations,
and automate them to reduce human efforts and cost by adopting related AWS services, third party
products, or custom tools (like
AWS CLI
or
AWS SDKs
).
Topics
Define a review process and analyze your workload regularly
Automating operations
Javascript is disabled or is unavailable in your browser.
To use the Amazon Web Services Documentation, Javascript must be enabled. Please refer to your browser's Help pages for instructions.
Document Conventions
COST09-BP03 Supply resources dynamically
Define a review process and analyze your workload regularly
