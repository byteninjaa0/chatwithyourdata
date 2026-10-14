"""Fallback fee tables when pickle files are not present."""

# Stream keys match the `child_education_nodes.py` lookups.
DEFAULT_GRADUATION_FEES = [
    {
        "graduation_destination": "International",
        "graduation_stream": "B.Tech",
        "current_fees_of_graduation": 10_826_849.5,
    },
    {
        "graduation_destination": "International",
        "graduation_stream": "MBBS",
        "current_fees_of_graduation": 17_615_234.87,
    },
    {
        "graduation_destination": "International",
        "graduation_stream": "B.Com / BBA",
        "current_fees_of_graduation": 10_968_112.54,
    },
    {
        "graduation_destination": "International",
        "graduation_stream": "Other",
        "current_fees_of_graduation": 7_200_561.0,
    },
    {
        "graduation_destination": "Domestic",
        "graduation_stream": "B.Tech",
        "current_fees_of_graduation": 1_282_600.0,
    },
    {
        "graduation_destination": "Domestic",
        "graduation_stream": "MBBS",
        "current_fees_of_graduation": 4_156_100.1,
    },
    {
        "graduation_destination": "Domestic",
        "graduation_stream": "B.Com / BBA",
        "current_fees_of_graduation": 225_849.0,
    },
    {
        "graduation_destination": "Domestic",
        "graduation_stream": "Other",
        "current_fees_of_graduation": 657_418.0,
    },
]

DEFAULT_POST_GRADUATION_FEES = [
    {
        "post_graduation_destination": "Domestic",
        "post_graduation_stream": "MBA",
        "current_fees_of_post_graduation": 1_500_000.0,
    },
    {
        "post_graduation_destination": "Domestic",
        "post_graduation_stream": "M.Tech",
        "current_fees_of_post_graduation": 1_200_000.0,
    },
    {
        "post_graduation_destination": "Domestic",
        "post_graduation_stream": "MD",
        "current_fees_of_post_graduation": 3_000_000.0,
    },
    {
        "post_graduation_destination": "Domestic",
        "post_graduation_stream": "Other",
        "current_fees_of_post_graduation": 1_200_000.0,
    },
    {
        "post_graduation_destination": "International",
        "post_graduation_stream": "MBA",
        "current_fees_of_post_graduation": 4_500_000.0,
    },
    {
        "post_graduation_destination": "International",
        "post_graduation_stream": "M.Tech",
        "current_fees_of_post_graduation": 4_000_000.0,
    },
    {
        "post_graduation_destination": "International",
        "post_graduation_stream": "MD",
        "current_fees_of_post_graduation": 5_000_000.0,
    },
    {
        "post_graduation_destination": "International",
        "post_graduation_stream": "Other",
        "current_fees_of_post_graduation": 4_000_000.0,
    },
]
