import json
import os

def convert_data_to_json(input_file="data.txt", output_file="data.json"):
    """
    Mengonversi data akun dari format teks ke format JSON.
    """
    accounts = []
    current_account = {}

    if not os.path.exists(input_file):
        print(f"Error: File `{input_file}` tidak ditemukan.")
        return

    try:
        with open(input_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:  # Baris kosong menandakan akhir blok akun
                    if current_account:
                        # Pastikan FID ada dan valid sebelum menambahkan
                        if "fid" in current_account and isinstance(current_account["fid"], int):
                            accounts.append(current_account)
                        else:
                            print(f"Peringatan: Akun dilewati karena FID tidak valid atau tidak ada: {current_account}")
                        current_account = {}
                    continue

                if line.startswith("PK: "):
                    current_account["private_key"] = line.replace("PK: ", "")
                elif line.startswith("Address: "):
                    current_account["wallet_address"] = line.replace("Address: ", "")
                elif line.startswith("Username: "): # Ini seharusnya FID
                    try:
                        current_account["fid"] = int(line.replace("Username: ", ""))
                    except ValueError:
                        print(f"Peringatan: Gagal mengonversi FID '{line.replace("Username: ", "")}' ke integer. Akun ini mungkin dilewati.")
                        current_account["fid"] = None # Tandai sebagai tidak valid
                elif line.startswith("FID: "): # Ini seharusnya Username
                    current_account["username"] = line.replace("FID: ", "")
                else:
                    print(f"Peringatan: Format baris tidak dikenal di `{input_file}`: {line}")
            
            # Tambahkan akun terakhir jika file tidak diakhiri dengan baris kosong
            if current_account:
                if "fid" in current_account and isinstance(current_account["fid"], int):
                    accounts.append(current_account)
                else:
                    print(f"Peringatan: Akun terakhir dilewati karena FID tidak valid atau tidak ada: {current_account}")

        with open(output_file, "w") as f:
            json.dump(accounts, f, indent=4)
        
        print(f"Berhasil mengonversi {len(accounts)} akun dari `{input_file}` ke `{output_file}`.")

    except Exception as e:
        print(f"Terjadi kesalahan saat mengonversi data: {e}")

if __name__ == "__main__":
    convert_data_to_json()