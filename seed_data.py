"""
QueueX Multi-Tenant College & 100-Student Seed Dataset
Provides realistic student directory for Apex Institute of Technology (AIT)
with unique student IDs, department distributions, and multi-tenant college linkage.
"""

from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random

PRIMARY_COLLEGE = {
    "code": "AIT",
    "name": "Apex Institute of Technology",
    "slug": "apex-tech",
    "domain": "ait.edu",
    "status": "active"
}

# 100 Realistic Students across 5 Departments
STUDENT_DATA_100 = [
    # Computer Science & Engineering (20: AIT-24-CS001 -> AIT-24-CS020)
    ("Aarav Sharma", "aarav.sharma@ait.edu", "9800010001", "24CS01", "Computer Science", "5th"),
    ("Diya Patel", "diya.patel@ait.edu", "9800010002", "24CS02", "Computer Science", "5th"),
    ("Rohan Verma", "rohan.verma@ait.edu", "9800010003", "24CS03", "Computer Science", "3rd"),
    ("Ishita Gupta", "ishita.gupta@ait.edu", "9800010004", "24CS04", "Computer Science", "3rd"),
    ("Aditya Malhotra", "aditya.malhotra@ait.edu", "9800010005", "24CS05", "Computer Science", "5th"),
    ("Sanya Kapoor", "sanya.kapoor@ait.edu", "9800010006", "24CS06", "Computer Science", "1st"),
    ("Varun Nair", "varun.nair@ait.edu", "9800010007", "24CS07", "Computer Science", "7th"),
    ("Pooja Choudhury", "pooja.choudhury@ait.edu", "9800010008", "24CS08", "Computer Science", "5th"),
    ("Karan Mehta", "karan.mehta@ait.edu", "9800010009", "24CS09", "Computer Science", "3rd"),
    ("Ananya Sen", "ananya.sen@ait.edu", "9800010010", "24CS10", "Computer Science", "1st"),
    ("Siddharth Rao", "siddharth.rao@ait.edu", "9800010011", "24CS11", "Computer Science", "7th"),
    ("Tanvi Bhatt", "tanvi.bhatt@ait.edu", "9800010012", "24CS12", "Computer Science", "5th"),
    ("Devansh Saxena", "devansh.saxena@ait.edu", "9800010013", "24CS13", "Computer Science", "3rd"),
    ("Rhea Ghosh", "rhea.ghosh@ait.edu", "9800010014", "24CS14", "Computer Science", "1st"),
    ("Manish Tiwari", "manish.tiwari@ait.edu", "9800010015", "24CS15", "Computer Science", "5th"),
    ("Sneha Kulkarni", "sneha.kulkarni@ait.edu", "9800010016", "24CS16", "Computer Science", "3rd"),
    ("Harsh Agarwal", "harsh.agarwal@ait.edu", "9800010017", "24CS17", "Computer Science", "7th"),
    ("Meera Nambiar", "meera.nambiar@ait.edu", "9800010018", "24CS18", "Computer Science", "5th"),
    ("Ayush Bansal", "ayush.bansal@ait.edu", "9800010019", "24CS19", "Computer Science", "3rd"),
    ("Kriti Singhania", "kriti.singhania@ait.edu", "9800010020", "24CS20", "Computer Science", "1st"),

    # AI & Data Science (20: AIT-24-AI021 -> AIT-24-AI040)
    ("Arjun Reddy", "arjun.reddy@ait.edu", "9800010021", "24AI01", "AI & Data Science", "3rd"),
    ("Zara Khan", "zara.khan@ait.edu", "9800010022", "24AI02", "AI & Data Science", "3rd"),
    ("Kabir Das", "kabir.das@ait.edu", "9800010023", "24AI03", "AI & Data Science", "1st"),
    ("Nisha Pillai", "nisha.pillai@ait.edu", "9800010024", "24AI04", "AI & Data Science", "5th"),
    ("Rishi Jain", "rishi.jain@ait.edu", "9800010025", "24AI05", "AI & Data Science", "5th"),
    ("Avani Joshi", "avani.joshi@ait.edu", "9800010026", "24AI06", "AI & Data Science", "3rd"),
    ("Pranav Mishra", "pranav.mishra@ait.edu", "9800010027", "24AI07", "AI & Data Science", "1st"),
    ("Divya Deshmukh", "divya.deshmukh@ait.edu", "9800010028", "24AI08", "AI & Data Science", "5th"),
    ("Kunal Pandey", "kunal.pandey@ait.edu", "9800010029", "24AI09", "AI & Data Science", "3rd"),
    ("Simran Gill", "simran.gill@ait.edu", "9800010030", "24AI10", "AI & Data Science", "1st"),
    ("Yuvraj Chauhan", "yuvraj.chauhan@ait.edu", "9800010031", "24AI11", "AI & Data Science", "5th"),
    ("Tara Iyer", "tara.iyer@ait.edu", "9800010032", "24AI12", "AI & Data Science", "3rd"),
    ("Nikhil Goel", "nikhil.goel@ait.edu", "9800010033", "24AI13", "AI & Data Science", "1st"),
    ("Palak Sethi", "palak.sethi@ait.edu", "9800010034", "24AI14", "AI & Data Science", "5th"),
    ("Samar Vohra", "samar.vohra@ait.edu", "9800010035", "24AI15", "AI & Data Science", "3rd"),
    ("Alia Fernandes", "alia.fernandes@ait.edu", "9800010036", "24AI16", "AI & Data Science", "1st"),
    ("Dhruv Somani", "dhruv.somani@ait.edu", "9800010037", "24AI17", "AI & Data Science", "5th"),
    ("Bhavna Menon", "bhavna.menon@ait.edu", "9800010038", "24AI18", "AI & Data Science", "3rd"),
    ("Gaurav Grover", "gaurav.grover@ait.edu", "9800010039", "24AI19", "AI & Data Science", "1st"),
    ("Juhi Trivedi", "juhi.trivedi@ait.edu", "9800010040", "24AI20", "AI & Data Science", "5th"),

    # Electronics & Communication (20: AIT-24-EC041 -> AIT-24-EC060)
    ("Omkar Bhosle", "omkar.bhosle@ait.edu", "9800010041", "24EC01", "Electronics & Communication", "5th"),
    ("Kashish Bajaj", "kashish.bajaj@ait.edu", "9800010042", "24EC02", "Electronics & Communication", "3rd"),
    ("Tejas Nadkarni", "tejas.nadkarni@ait.edu", "9800010043", "24EC03", "Electronics & Communication", "7th"),
    ("Gauri Sundaram", "gauri.sundaram@ait.edu", "9800010044", "24EC04", "Electronics & Communication", "5th"),
    ("Abhay Sinha", "abhay.sinha@ait.edu", "9800010045", "24EC05", "Electronics & Communication", "1st"),
    ("Natasha Dsouza", "natasha.dsouza@ait.edu", "9800010046", "24EC06", "Electronics & Communication", "3rd"),
    ("Chirag Singhal", "chirag.singhal@ait.edu", "9800010047", "24EC07", "Electronics & Communication", "5th"),
    ("Mansi Shrestha", "mansi.shrestha@ait.edu", "9800010048", "24EC08", "Electronics & Communication", "7th"),
    ("Tushar Hegde", "tushar.hegde@ait.edu", "9800010049", "24EC09", "Electronics & Communication", "1st"),
    ("Shreya Kamath", "shreya.kamath@ait.edu", "9800010050", "24EC10", "Electronics & Communication", "3rd"),
    ("Aakash Bhatnagar", "aakash.bhatnagar@ait.edu", "9800010051", "24EC11", "Electronics & Communication", "5th"),
    ("Leena Cherian", "leena.cherian@ait.edu", "9800010052", "24EC12", "Electronics & Communication", "3rd"),
    ("Vikas Prajapati", "vikas.prajapati@ait.edu", "9800010053", "24EC13", "Electronics & Communication", "1st"),
    ("Anushka Rawat", "anushka.rawat@ait.edu", "9800010054", "24EC14", "Electronics & Communication", "5th"),
    ("Deepak Murthy", "deepak.murthy@ait.edu", "9800010055", "24EC15", "Electronics & Communication", "7th"),
    ("Swati Pathak", "swati.pathak@ait.edu", "9800010056", "24EC16", "Electronics & Communication", "3rd"),
    ("Sachin Jadhav", "sachin.jadhav@ait.edu", "9800010057", "24EC17", "Electronics & Communication", "1st"),
    ("Urvi Sheth", "urvi.sheth@ait.edu", "9800010058", "24EC18", "Electronics & Communication", "5th"),
    ("Hemant Barman", "hemant.barman@ait.edu", "9800010059", "24EC19", "Electronics & Communication", "3rd"),
    ("Vidya Raghavan", "vidya.raghavan@ait.edu", "9800010060", "24EC20", "Electronics & Communication", "1st"),

    # Mechanical Engineering (20: AIT-24-ME061 -> AIT-24-ME080)
    ("Rajesh Solanki", "rajesh.solanki@ait.edu", "9800010061", "24ME01", "Mechanical Engineering", "5th"),
    ("Payal Rathore", "payal.rathore@ait.edu", "9800010062", "24ME02", "Mechanical Engineering", "3rd"),
    ("Ashwin Chawla", "ashwin.chawla@ait.edu", "9800010063", "24ME03", "Mechanical Engineering", "7th"),
    ("Kiran Mathur", "kiran.mathur@ait.edu", "9800010064", "24ME04", "Mechanical Engineering", "5th"),
    ("Saurabh Kaul", "saurabh.kaul@ait.edu", "9800010065", "24ME05", "Mechanical Engineering", "1st"),
    ("Preeti Lodha", "preeti.lodha@ait.edu", "9800010066", "24ME06", "Mechanical Engineering", "3rd"),
    ("Naveen Yadav", "naveen.yadav@ait.edu", "9800010067", "24ME07", "Mechanical Engineering", "5th"),
    ("Richa Shukla", "richa.shukla@ait.edu", "9800010068", "24ME08", "Mechanical Engineering", "7th"),
    ("Ganesh Gokhale", "ganesh.gokhale@ait.edu", "9800010069", "24ME09", "Mechanical Engineering", "1st"),
    ("Namrata Oberoi", "namrata.oberoi@ait.edu", "9800010070", "24ME10", "Mechanical Engineering", "3rd"),
    ("Praveen Soni", "praveen.soni@ait.edu", "9800010071", "24ME11", "Mechanical Engineering", "5th"),
    ("Esha Deol", "esha.deol@ait.edu", "9800010072", "24ME12", "Mechanical Engineering", "3rd"),
    ("Mohit Rathi", "mohit.rathi@ait.edu", "9800010073", "24ME13", "Mechanical Engineering", "1st"),
    ("Kavita Bist", "kavita.bist@ait.edu", "9800010074", "24ME14", "Mechanical Engineering", "5th"),
    ("Rohit Gusain", "rohit.gusain@ait.edu", "9800010075", "24ME15", "Mechanical Engineering", "7th"),
    ("Isha Negi", "isha.negi@ait.edu", "9800010076", "24ME16", "Mechanical Engineering", "3rd"),
    ("Ankit Kandari", "ankit.kandari@ait.edu", "9800010077", "24ME17", "Mechanical Engineering", "1st"),
    ("Deepa Chamoli", "deepa.chamoli@ait.edu", "9800010078", "24ME18", "Mechanical Engineering", "5th"),
    ("Umesh Pant", "umesh.pant@ait.edu", "9800010079", "24ME19", "Mechanical Engineering", "3rd"),
    ("Shalini Thapa", "shalini.thapa@ait.edu", "9800010080", "24ME20", "Mechanical Engineering", "1st"),

    # Civil Engineering (20: AIT-24-CE081 -> AIT-24-CE100)
    ("Bhavesh Joshi", "bhavesh.joshi@ait.edu", "9800010081", "24CE01", "Civil Engineering", "5th"),
    ("Komal Sahu", "komal.sahu@ait.edu", "9800010082", "24CE02", "Civil Engineering", "3rd"),
    ("Sanjay Maurya", "sanjay.maurya@ait.edu", "9800010083", "24CE03", "Civil Engineering", "7th"),
    ("Bina Baghel", "bina.baghel@ait.edu", "9800010084", "24CE04", "Civil Engineering", "5th"),
    ("Manoj Kushwaha", "manoj.kushwaha@ait.edu", "9800010085", "24CE05", "Civil Engineering", "1st"),
    ("Sheetal Prajapati", "sheetal.prajapati@ait.edu", "9800010086", "24CE06", "Civil Engineering", "3rd"),
    ("Anand Nishad", "anand.nishad@ait.edu", "9800010087", "24CE07", "Civil Engineering", "5th"),
    ("Rekha Bind", "rekha.bind@ait.edu", "9800010088", "24CE08", "Civil Engineering", "7th"),
    ("Dinesh Rajbhar", "dinesh.rajbhar@ait.edu", "9800010089", "24CE09", "Civil Engineering", "1st"),
    ("Poonam Saroj", "poonam.saroj@ait.edu", "9800010090", "24CE10", "Civil Engineering", "3rd"),
    ("Mukesh Paswan", "mukesh.paswan@ait.edu", "9800010091", "24CE11", "Civil Engineering", "5th"),
    ("Sunita Rawat", "sunita.rawat@ait.edu", "9800010092", "24CE12", "Civil Engineering", "3rd"),
    ("Vinod Valmiki", "vinod.valmiki@ait.edu", "9800010093", "24CE13", "Civil Engineering", "1st"),
    ("Babita Dhobi", "babita.dhobi@ait.edu", "9800010094", "24CE14", "Civil Engineering", "5th"),
    ("Rakesh Khatik", "rakesh.khatik@ait.edu", "9800010095", "24CE15", "Civil Engineering", "7th"),
    ("Geeta Kori", "geeta.kori@ait.edu", "9800010096", "24CE16", "Civil Engineering", "3rd"),
    ("Santosh Chamar", "santosh.chamar@ait.edu", "9800010097", "24CE17", "Civil Engineering", "1st"),
    ("Lalita Bahelia", "lalita.bahelia@ait.edu", "9800010098", "24CE18", "Civil Engineering", "5th"),
    ("Ajay Dhanuk", "ajay.dhanuk@ait.edu", "9800010099", "24CE19", "Civil Engineering", "3rd"),
    ("Rita Dom", "rita.dom@ait.edu", "9800010100", "24CE20", "Civil Engineering", "1st"),
]


def generate_unique_id(index, dept):
    dept_prefix = {
        "Computer Science": "CS",
        "AI & Data Science": "AI",
        "Electronics & Communication": "EC",
        "Mechanical Engineering": "ME",
        "Civil Engineering": "CE",
    }.get(dept, "GEN")
    return f"AIT-24-{dept_prefix}{index:03d}"


def seed_primary_college(conn):
    """Ensure Apex Institute of Technology exists in `colleges` table."""
    c = conn.cursor()
    c.execute("SELECT id FROM colleges WHERE code = ?", (PRIMARY_COLLEGE["code"],))
    row = c.fetchone()
    if row:
        return row["id"]

    c.execute(
        """INSERT INTO colleges (code, name, slug, domain, status)
           VALUES (?, ?, ?, ?, ?)""",
        (
            PRIMARY_COLLEGE["code"],
            PRIMARY_COLLEGE["name"],
            PRIMARY_COLLEGE["slug"],
            PRIMARY_COLLEGE["domain"],
            PRIMARY_COLLEGE["status"],
        )
    )
    conn.commit()
    return c.lastrowid


def seed_100_students(conn):
    """Seed 100 realistic student records if not already populated."""
    college_id = seed_primary_college(conn)
    c = conn.cursor()

    # Backfill any existing student without student_uid
    c.execute("SELECT id, roll_no FROM users WHERE role = 'student' AND student_uid IS NULL")
    for r in c.fetchall():
        gen_uid = f"AIT-24-ST{r['id']:03d}"
        c.execute("UPDATE users SET student_uid = ?, college_id = ? WHERE id = ?", (gen_uid, college_id, r["id"]))
    conn.commit()

    c.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'student' AND student_uid IS NOT NULL")
    existing_count = c.fetchone()["cnt"]

    if existing_count >= 100:
        return existing_count

    default_pw_hash = generate_password_hash("student123")
    now_iso = datetime.now().isoformat(timespec="seconds")

    dept_counters = {}
    for item in STUDENT_DATA_100:
        full_name, email, phone, roll_no, dept, sem = item
        dept_counters[dept] = dept_counters.get(dept, 0) + 1
        student_uid = generate_unique_id(dept_counters[dept], dept)

        c.execute("SELECT id FROM users WHERE email = ? OR roll_no = ? OR student_uid = ?", (email, roll_no, student_uid))
        if not c.fetchone():
            c.execute(
                """INSERT INTO users (full_name, email, phone, password_hash, role, roll_no, department, semester, student_uid, college_id, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'student', ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (
                    full_name,
                    email,
                    phone,
                    default_pw_hash,
                    roll_no,
                    dept,
                    sem,
                    student_uid,
                    college_id,
                    now_iso,
                    now_iso,
                ),
            )
    conn.commit()
    return 100

