#!/usr/bin/env python
import re

with open('src/splink_model.py', 'r') as f:
    content = f.read()

old_block = """        # Fuzzy match untuk typo: JW >= 0.92 dan JW >= 0.85
        fuzzy_high = (
            "(first_name_std_l IS NOT NULL AND first_name_std_r IS NOT NULL "
            "AND last_name_std_l IS NOT NULL AND last_name_std_r IS NOT NULL "
            "AND jaro_winkler_similarity(first_name_std_l || ' ' || last_name_std_l, "
            "                             first_name_std_r || ' ' || last_name_std_r) >= 0.92)"
        )
        fuzzy_med = (
            "(first_name_std_l IS NOT NULL AND first_name_std_r IS NOT NULL "
            "AND last_name_std_l IS NOT NULL AND last_name_std_r IS NOT NULL "
            "AND jaro_winkler_similarity(first_name_std_l || ' ' || last_name_std_l, "
            "                             first_name_std_r || ' ' || last_name_std_r) >= 0.85)"
        )
        levels = [
            CustomLevel(both_null, label_for_charts="nama kosong").configure(is_null_level=True),
            CustomLevel(exact, label_for_charts="ejaan persis").configure(m_probability=0.70),
            CustomLevel(first_only, label_for_charts="first name sama saja").configure(m_probability=0.40),
            CustomLevel(last_only, label_for_charts="last name sama saja").configure(m_probability=0.40),
            CustomLevel(fuzzy_high, label_for_charts="JW >= 0.92").configure(m_probability=0.45),
            CustomLevel(fuzzy_med, label_for_charts="JW >= 0.85").configure(m_probability=0.30),
            ElseLevel().configure(m_probability=0.05),
        ]
        comparisons.append(cl.CustomComparison(comparison_levels=levels, output_column_name="name"))"""

new_block = """        # Fuzzy jaro-winkler untuk typo
        fuzzy = (
            "(first_name_std_l IS NOT NULL AND first_name_std_r IS NOT NULL "
            "AND last_name_std_l IS NOT NULL AND last_name_std_r IS NOT NULL "
            "AND jaro_winkler_similarity(first_name_std_l || ' ' || last_name_std_l, "
            "                             first_name_std_r || ' ' || last_name_std_r) >= 0.85)"
        )
        levels = [
            CustomLevel(both_null, label_for_charts="nama kosong").configure(is_null_level=True),
            CustomLevel(exact, label_for_charts="ejaan persis").configure(m_probability=0.70),
            CustomLevel(fuzzy, label_for_charts="fonetik/typos").configure(m_probability=0.35),
            ElseLevel().configure(m_probability=0.05),
        ]
        comparisons.append(cl.CustomComparison(comparison_levels=levels, output_column_name="name"))"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open('src/splink_model.py', 'w') as f:
        f.write(content)
    print("Replacement successful")
else:
    print("Old block not found")
    # Debug: check what's in the name section
    idx = content.find("# Fuzzy match untuk typo")
    if idx >= 0:
        print(f"Found at {idx}, context: {content[idx:idx+500]}")
    else:
        print("Can't find the block at all")