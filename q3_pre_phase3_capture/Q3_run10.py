# Q3 run 10/10
# status: FAIL  latency: 14.9s
# query: We're heading into IPO. Which of our biggest accounts in regulated Asian markets are being managed by people who don't have ESOPs and haven't bothered with any certifications?
# ------------------------------------------------------------------------

tier1_asia = df_customers[
    (df_customers['tier'] == 'Tier 1') &
    (df_customers['country'].isin(['India', 'Japan', 'South Korea']))
].copy()

with_am = tier1_asia.merge(
    df_employees[['employee_id', 'first_name', 'last_name', 'level', 'job_title', 'department_id']],
    left_on='account_manager_employee_id',
    right_on='employee_id',
    how='left'
)

no_esop = with_am[~with_am['level'].isin(['L5', 'L6', 'L7', 'L8'])].copy()

non_completed_cert_emp_ids = set(
    df_training_compliance[
        (df_training_compliance['module_name'].isin([
            'AWS Solutions Architect (Professional)',
            'CIPP/A',
            'CKA - Kubernetes Administrator',
            'Google Professional ML Engineer'
        ])) &
        (df_training_compliance['status'] != 'Completed')
    ]['employee_id'].dropna().unique()
)

result = (
    no_esop[no_esop['employee_id'].isin(non_completed_cert_emp_ids)][
        ['customer_id', 'customer_name', 'country', 'tier', 'arr_inr_lakhs',
         'employee_id', 'first_name', 'last_name', 'level', 'job_title']
    ]
    .drop_duplicates(subset=['customer_id'])
    .sort_values('arr_inr_lakhs', ascending=False)
    .reset_index(drop=True)
)